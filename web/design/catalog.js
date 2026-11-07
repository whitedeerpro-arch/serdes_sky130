// Generated data; edit config/design_catalog.json and module records.
window.DESIGN_CATALOG = {
  "schema": 1,
  "project": {
    "name": "Simple SerDes",
    "subtitle": "SKY130 · 1.8 V · 4 Gb/s",
    "description": "以模块边界组织设计，以模型规划参数，用局部仿真验证迭代。",
    "updated": "2026-11-07"
  },
  "nodes": [
    {
      "id": "serdes",
      "parent": null,
      "name": "SerDes",
      "subtitle": "16:1 TX · 四相半速 RX · 共享 PLL",
      "state": "模块开发",
      "summary": "250 MHz 参考产生 2 GHz 多相时钟，发送端串化 16 位字，接收端以独立 PI-CDR 恢复数据。各子系统通过明确的激励、负载和测量边界独立推进。",
      "facts": {
        "设计": "模块分层推进",
        "PVT": "按模块与工况记录",
        "失配": "偏置与 RX 已有局部分析",
        "噪声": "VCO 已有模型与预算"
      },
      "boundary": {
        "inputs": [
          "250 MHz 参考；16 位并行 TX 数据；远端 4 Gb/s 差分数据"
        ],
        "outputs": [
          "100 Ω 差分线；恢复字时钟域 16 位 RX 数据"
        ],
        "assumptions": [
          "4 Gb/s 原始线速，不含编码；信道以 C2 为设计起点。",
          "模块集成与某次参数改进的验证范围分别记录，不要求每一步都做整机长仿真。"
        ]
      },
      "planning": {
        "question": "怎样通过可信的模块边界拆解设计成本？",
        "model": "约束与粗模型 → 参数求解 → 局部电路校准 → 边界回归。",
        "parameters": "250 MHz 参考、2 GHz 半速时钟、250 ps UI、16 bit 字。",
        "verification": "优先在暴露问题的工况验证模块；按需要选择短联合测试。"
      },
      "references": [
        {
          "title": "架构与接口",
          "path": "docs/overview/architecture.md"
        },
        {
          "title": "规格",
          "path": "docs/overview/spec.md"
        },
        {
          "title": "尺寸设计方法",
          "path": "docs/verification/sizing.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "tx",
      "parent": "serdes",
      "name": "TX",
      "subtitle": "并行输入 → 16:1 串化 → 线驱动",
      "state": "迭代推进",
      "summary": "新字入口已接实际v3与完整串化/驱动：TT位序/眼图通过，FS热角暴露半字边界低裕量；物理guard映射SS时序不足，优先局部归因与接口校准。",
      "facts": {
        "设计": "串化 / 线驱动已实现",
        "PVT": "r2 固定时钟边界 45 点",
        "失配": "局部统计待补",
        "噪声": "时钟路径预算待校准"
      },
      "boundary": {
        "inputs": [
          "16 位 CMOS 字；250M/500M/1G/2G 选择时钟；模块偏置"
        ],
        "outputs": [
          "4 Gb/s NRZ，源端 2×50 Ω，约 400 mVpp 差分目标"
        ],
        "assumptions": [
          "r2 的 45 点使用同一份理想化 TT 时钟边界。",
          "数据到达时刻、选择时钟相对位置、驱动负载应分别明确。"
        ]
      },
      "planning": {
        "question": "哪种时钟构造使各路 PVT 漂移自然抵消？",
        "model": "serdes_flow.balance 比较路径组成，再以单元实测延迟校准。",
        "parameters": "分频级数、clk→q、buffer 延迟、数据入口 clk→q 与扇出。",
        "verification": "同时检查眼图健康和 bit_mapping；局部通过后扩角。"
      },
      "references": [
        {
          "title": "TX 工作修订",
          "path": "config/tx_working_revision.toml"
        },
        {
          "title": "串化器",
          "path": "docs/design/tx_serializer.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "bias",
      "parent": "serdes",
      "name": "Bias",
      "subtitle": "带隙 · 恒 I·R · 电流分配 · 参考缓冲",
      "state": "结构已实现",
      "summary": "以带隙和同类电阻定义恒 I·R 电流，将电流分配到各模块的本地二极管。RX 共模与 LF 预充由独立参考缓冲提供。",
      "facts": {
        "设计": "参考 / 分配 / 缓冲已有",
        "PVT": "DC 与上电 135 条件",
        "失配": "200 样本与配对温漂",
        "噪声": "PSRR 已表征"
      },
      "boundary": {
        "inputs": [
          "1.65–1.95 V 电源；5 bit r_ref 修调码；各支路实际负载"
        ],
        "outputs": [
          "CML 212.5 µA、CTLE/CP 50 µA 拷贝；vcm 1.05 V；B2 预充参考"
        ],
        "assumptions": [
          "恒 I·R 保持静态摆幅代理，不保证恒速度。",
          "PNP 模型没有失配项；共享参考误差在各支路间相关。"
        ]
      },
      "planning": {
        "question": "应保持恒电流还是恒摆幅，误差怎样分配？",
        "model": "器件卡 / gm-ID / 电阻温漂 → 拓扑约束 → 放大器环路与修调范围。",
        "parameters": "N=8，r_ref 5 bit，核心补偿与分配栅负载共同确定稳定性。",
        "verification": "DC、上电、供电阶跃、局部 MC 与修调后的配对温漂。"
      },
      "references": [
        {
          "title": "偏置设计",
          "path": "docs/design/bias.md"
        },
        {
          "title": "工作修订",
          "path": "config/bias_working_revision.toml"
        }
      ],
      "iterations": []
    },
    {
      "id": "rx",
      "parent": "serdes",
      "name": "RX",
      "subtitle": "CTLE → PI 采样 → 物理读出 → CDR",
      "state": "迭代推进",
      "summary": "四相采样与物理 deser16 将高速模拟判决转为恢复字时钟域的数据和边沿票。独立 PI 跟踪每一路远端频偏。",
      "facts": {
        "设计": "ac_trim / c2 / deser16",
        "PVT": "采样窗口 135 条件",
        "失配": "CTLE / 采样 / 校准分析已有",
        "噪声": "孔径与联合噪声待补"
      },
      "boundary": {
        "inputs": [
          "AC 耦合远端差分数据；四对相位锚点；vcm 与局部偏置"
        ],
        "outputs": [
          "16 位数据、恢复字时钟；PI 调相控制与锁定状态"
        ],
        "assumptions": [
          "当前模块表征主要使用理想相关锚点或登记的 C2 远端边界。",
          "窗口、读出和动态 CDR 各自有不同测试边界，分别引用。"
        ]
      },
      "planning": {
        "question": "怎样将采样、读出和控制路径放在各自可行的时序域？",
        "model": "共模可行区、时钟 buffer 粗模型、读出位映射与时序规划。",
        "parameters": "PI 64 码；cmix 120 fF；c2 AC 时钟；读出 ÷2 保持 W40。",
        "verification": "压力角窗口全扫、其余门槛；读出逐位检查；短时物理闭环配合长时行为模型。"
      },
      "references": [
        {
          "title": "RX 工作修订",
          "path": "config/rx_working_revision.toml"
        },
        {
          "title": "PI / 采样 / 读出",
          "path": "docs/design/rx_pi_sampler.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll",
      "parent": "serdes",
      "name": "PLL",
      "subtitle": "PFD / CP / LF / VCO / ÷8 / 粗调码",
      "state": "顶层集成已有",
      "summary": "PLL 已有完整电路顶层，包含 VCO、粗调码接口、分频反馈、PFD、CP 和 LF，并有带双节点预充的启动顶层。近期按模块改进 VCO 工作区与环路参数。",
      "facts": {
        "设计": "完整 PLL 顶层已具备",
        "PVT": "分模块网格 + 分层闭环",
        "失配": "VCO / CP 局部 MC 待补",
        "噪声": "ISF + 环路 / CDR 模型"
      },
      "boundary": {
        "inputs": [
          "250 MHz 参考；粗调码；局部偏置；reset / CP enable / 预充控制"
        ],
        "outputs": [
          "2 GHz 四对八相；250 MHz 反馈；Vctrl 与锁定测量接口"
        ],
        "assumptions": [
          "保留已有 PLL 集成与闭环证据；近期参数改进在子模块下附着。",
          "近锁初始化、分层模型捕获、从零上电是不同验证场景。"
        ]
      },
      "planning": {
        "question": "怎样联合选择工作点、Kvco、CP 电流、LF 和预充目标？",
        "model": "实测 VCO 曲线作为 plant，实际 PFD/CP 与 LF 做分层捕获；线性模型比较带宽、稳定性与噪声。",
        "parameters": "÷8；50 µA / 6.5 kΩ / 40p+2p 为已有实现；k2/3/4 为近期环路改进比较。",
        "verification": "模块工作区和电荷测试 → 分层闭环 → 有判别力的原生短联合验证。"
      },
      "references": [
        {
          "title": "完整 PLL 核心",
          "path": "analog/pll/top/spice/pll_balanced_core.spice"
        },
        {
          "title": "带预充的完整核心",
          "path": "analog/pll/top/spice/pll_balanced_startup_core.spice"
        },
        {
          "title": "环路设计与验证",
          "path": "docs/design/pll_loop.md"
        }
      ],
      "iterations": [
        {
          "id": "pll-top-existing",
          "title": "完整 PLL 与启动顶层",
          "date": "2026-10-28",
          "phase": "validation",
          "problem": "将环振、分频反馈、鉴相、电荷泵和滤波器组成可复用子系统。",
          "model": "先用 VCO plant 做捕获，再在原生电路接回。",
          "changes": "完整 pll_balanced_core；另有双节点预充与 CP 门控顶层。",
          "validation": "TT 近锁初始化的原生持续判据；后续 r3 分层闭环 4 工况×3 初值。",
          "conclusion": "PLL 顶层集成已经具备。后续尺寸与参数改进分别跟踪验证。",
          "attachments": [
            {
              "title": "已有原生 PLL 记录",
              "path": "docs/history/physical_clock_distribution_results.md"
            },
            {
              "title": "环路 PVT",
              "path": "docs/history/pll_loop_pvt.md"
            }
          ]
        }
      ]
    },
    {
      "id": "channel",
      "parent": "serdes",
      "name": "Channel",
      "subtitle": "端接 / PCB / 封装边界",
      "state": "模型已建立",
      "summary": "以近无损 RLC16 支持 TX 局部回归，以 C0–C5 合成 PCB 族研究损耗、支路和偏斜。C2 是当前 RX 设计起点。",
      "facts": {
        "设计": "合成被动模型",
        "PVT": "模型与接口表征",
        "失配": "板线容差待定义",
        "噪声": "不含串扰"
      },
      "boundary": {
        "inputs": [
          "TX 源阻抗、pad/封装代理、AC 耦合"
        ],
        "outputs": [
          "接收端差分电压与输入阻抗"
        ],
        "assumptions": [
          "C2：2 GHz 插损 6 dB；不是具体板线提取。",
          "回放边界应登记源修订、负载签名和适用工况。"
        ]
      },
      "planning": {
        "question": "在固定源和接收负载下，ISI 如何影响眼图？",
        "model": "被动 RLC / Foster 模型、S 参数、脉冲响应与有限记忆叠加。",
        "parameters": "损耗、延时、支路、偏斜、端接和封装。",
        "verification": "AC / 无源性 / 脉冲与实际驱动局部联调。"
      },
      "references": [
        {
          "title": "信道模型",
          "path": "docs/design/channel_model.md"
        },
        {
          "title": "边界条件登记",
          "path": "config/boundary_conditions.json"
        }
      ],
      "iterations": []
    },
    {
      "id": "tx.capture",
      "parent": "tx",
      "name": "并行字捕获",
      "key": "T01",
      "subtitle": "同沿完整捕获 · 两组互补保持",
      "state": "完整树接口验证",
      "summary": "首级六压力48字、B关闭12组；完整TX原FS眼图失败已定位末级，时钟改进后TT/FS/SS冷过眼图门槛。guard回放非物理路径，SS映射时序仍不足。",
      "facts": {
        "设计": "16位保持入口＋完整TX候选",
        "PVT": "首级6压力；整链extra3 TT/FS/SS冷眼图过",
        "失配": "待时序预算",
        "噪声": "归入发数抖动"
      },
      "boundary": {
        "inputs": [
          "PHY字时钟域16位CMOS数据；250MHz CML选择；局部偏置"
        ],
        "outputs": [
          "A低8位／B高8位，按首级选中半周期保持有效"
        ],
        "assumptions": [
          "上游FIFO/CDC另行实现；输出不是任意时刻同一字的普通16位总线。",
          "数据DFF无复位，guard在真实下降沿后开放；当前控制数据/标签为RTL波形回放，尚无物理标签与驱动blank。",
          "首级局部实验用5fF代理；完整树候选已使用实际后级和线驱动/RLC16。输入为理想2GHz，计数器带初态，非PLL启动。"
        ]
      },
      "planning": {
        "question": "实际接收延迟与同沿捕获是否保持被选中的旧半字？",
        "model": "单元卡与balance区间比较；两组8位互补保持扩展建立时间。",
        "parameters": "两级数据延迟、本地互补时钟、接收器与bank缓冲负载。",
        "verification": "先用FS逐位诊断定位半字边界，补转换器/树内部观察再局部修复；物理控制先校准接口参数，之后扩角/统计/噪声。"
      },
      "references": [
        {
          "title": "TX 串化器接口",
          "path": "docs/design/tx_serializer.md"
        },
        {
          "title": "入口单元与结构选择",
          "path": "docs/design/tx_ingress.md"
        },
        {
          "title": "可外发的可行区模型",
          "path": "docs/work_packages/WP-004-tx-capture-model.md"
        },
        {
          "title": "完整字与分组保持原型",
          "path": "docs/design/tx_word_capture.md"
        },
        {
          "title": "原始跨字波形",
          "path": "docs/figures/tx/ingress/tx_staggered_hold_timing.png"
        },
        {
          "title": "可外发的原始波形复核",
          "path": "docs/work_packages/WP-005-tx-staggered-waveform-audit.md"
        },
        {
          "title": "B关闭竞争与边界",
          "path": "docs/design/tx_launch_hold.md"
        },
        {
          "title": "关闭竞争可行区",
          "path": "docs/figures/tx/ingress/tx_launch_hold_aperture.png"
        },
        {
          "title": "字入口保护RTL",
          "path": "digital/tx/README.md"
        },
        {
          "title": "控制器本地review",
          "path": "docs/work_packages/reviews/tx-ingress-control.md"
        },
        {
          "title": "完整TX接口与三处眼图",
          "path": "docs/design/tx_parallel_serializer.md"
        },
        {
          "title": "完整TX眼图",
          "path": "docs/figures/tx/ingress/tx_parallel_serializer_eye.png"
        },
        {
          "title": "Guard映射时序可行性",
          "path": "docs/work_packages/deliveries/tx-ingress-timing.md"
        }
      ],
      "iterations": [
        {
          "id": "20261106T195211Z_857fbd499f",
          "module": "tx.capture",
          "date": "2026-11-07",
          "timestamp": "2026-11-06T19:52:11.672747+00:00",
          "title": "实际负载下比较精简与复位DFF，准备字更新约束",
          "phase": "validation",
          "problem": "现有串化输入仍是理想发数或静态首字，未实现字入口；缺实际加载后的捕获/转换延迟与字时钟扇出边界。",
          "model": "同端口30ps时钟，两种已有DFF分别驱动真实CMOS/CML和首级MUX输入，静态选中/未选中对照；下游5fF代理。先用单元card校准结构模型，再检查允许字更新窗。",
          "changes": "保留既有器件尺寸，新增有真实偏置/PDK R tt的入口单元card，按工艺角合并并限制2 worker；精简无复位数据DFF列为优先候选，未采用完整16位入口。",
          "validation": "6压力条件×2加载状态12例完整，共120次捕获正确；Q/CML每次捕获后1ns内均恰有一次交越。精简型时钟到CML 91–281ps，复位型216–788ps。单DFF时钟电荷等效5.7–8.7fF，16路约91–139fF，未含额外负载。",
          "conclusion": "优先考察精简数据存储并明确valid/启动屏蔽。实际时钟驱动、更新窗、孔径、位映射与跨字一致性仍未测。WP-004已给出可外发的固定相位可行区约束，不冒充动态设计证明。",
          "attachments": [
            {
              "title": "入口设计与单元边界",
              "path": "docs/design/tx_ingress.md"
            },
            {
              "title": "实测延迟图",
              "path": "docs/figures/tx/ingress/tx_ingress_loaded_delay.png"
            },
            {
              "title": "单元数据",
              "path": "docs/data/tx_ingress_card.json"
            },
            {
              "title": "事实review",
              "path": "docs/work_packages/reviews/WP-002.md"
            },
            {
              "title": "可外发约束包",
              "path": "docs/work_packages/WP-004-tx-capture-model.md"
            }
          ]
        },
        {
          "id": "20261106T204112Z_f8240c9507",
          "module": "tx.capture",
          "date": "2026-11-07",
          "timestamp": "2026-11-06T20:41:12.588810+00:00",
          "title": "16位捕获与分组保持：实际字时钟六压力点通过",
          "phase": "validation",
          "problem": "旧串化bench依赖理想发数时刻，单元延迟不能直接证明完整字入口；同沿捕获下一字时B组必须继续保持旧字。",
          "model": "单元实测与balance固定窗口比较：精简型CML窗至少约190ps但实际公共窗未知，改用两组8位在未选中半周期更新。",
          "changes": "16个精简DFF＋两级数据反相器＋互补静态launch锁存；既有250MHz CML接收器与两级8/16、24/48um缓冲驱动整个bank；八个实际首级MUX。",
          "validation": "真实偏置/PDK R tt，理想400mVpp CML源，Q线2fF/MUX输出每端5fF代理。统一预热1周期，6压力条件40ns共48字768bit一致；输入保持全部通过。B关闭→数据最小55.62ps仅诊断。67项软件测试通过。",
          "conclusion": "局部原型成立，未接完整串化链。无预热TT首字失败单独保留；硬件有效字控制、孔径、45PVT、失配/噪声与完整眼图待做。WP-005已准备外发，0仿真配额。",
          "attachments": [
            {
              "title": "原型设计与边界",
              "path": "docs/design/tx_word_capture.md"
            },
            {
              "title": "实际跨字波形",
              "path": "docs/figures/tx/ingress/tx_staggered_hold_timing.png"
            },
            {
              "title": "小数据与来源哈希",
              "path": "docs/data/tx_staggered_ingress.json"
            },
            {
              "title": "外发原始复核包",
              "path": "docs/work_packages/WP-005-tx-staggered-waveform-audit.md"
            }
          ]
        },
        {
          "id": "20261107T043005Z_5677444ca3",
          "module": "tx.capture",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T04:30:05.038917+00:00",
          "title": "B关闭12组边界与字入口保护RTL",
          "phase": "validation",
          "problem": "正常关闭→数据交越间隔不能直接当作保持裕量；首字预热需要控制实现，并区分A/B在飞字标签。",
          "model": "完整bank实际CLK/CLK_b与伙伴/选择切片，保留一周期历史，先原样校准再平移数据；A正沿/B负沿标签独立流水。",
          "changes": "新增加载B切片及登记边界v3；PWL有界简化/长向量和逐路比对；下降沿预热guard RTL，组合idle数据，A/B标签；主16位DUT尺寸未改。",
          "validation": "六压力两方向14原样校准＋164平移点，12组夹住边界；完整所选窗口独立复测无分歧。最小正常到达距已测保持点70.45ps，仅固定电压回放。控制RTL149项断言、lint/结构通过；软件73测试通过。",
          "conclusion": "继续完整树动态接入。源阻抗/其他形状/失配/噪声、45角、输入建立保持、标签与driver blank、CDC/STA仍未闭合。",
          "attachments": [
            {
              "title": "保持边界与证据",
              "path": "docs/design/tx_launch_hold.md"
            },
            {
              "title": "六角关闭竞争图",
              "path": "docs/figures/tx/ingress/tx_launch_hold_aperture.png"
            },
            {
              "title": "小数据与哈希",
              "path": "docs/data/tx_launch_hold_aperture.json"
            },
            {
              "title": "控制器review",
              "path": "docs/work_packages/reviews/tx-ingress-control.md"
            }
          ]
        },
        {
          "id": "20261107T053024Z_98a9a6da3e",
          "module": "tx.capture",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T05:30:24.298980+00:00",
          "title": "实际v3与完整TX接入：TT自然位序和眼图",
          "phase": "validation",
          "problem": "首级代理负载不能证明完整串化逐位顺序与眼图，需要接实际分发和后级。",
          "model": "固定已登记的实际字时钟事件，运行guard RTL产生输入；由实际捕获字构造序列，训练定相位，另测bit_mapping。",
          "changes": "新capture_serializer16将字时钟接收、16位捕获/互补保持、转换器和完整树连接，bench保留真实驱动/RLC16。",
          "validation": "TT1.8V27°C、真实偏置/PDKRtt、理想2GHz源、计数器初态；120ns22有效字，256payload零错；三节点自然位序，153.71/194.30/193.89mV及0.02930/0.03235/0.03437UI。",
          "conclusion": "整链接口候选成立于TT；扩压力角与45点，物理控制/blank和噪声/MC仍缺。旧r2八置换表不插入v3。",
          "attachments": [
            {
              "title": "tx_parallel_serializer.md",
              "path": "docs/design/tx_parallel_serializer.md"
            },
            {
              "title": "tx_parallel_serializer_eye.png",
              "path": "docs/figures/tx/ingress/tx_parallel_serializer_eye.png"
            },
            {
              "title": "tx_parallel_serializer.json",
              "path": "results/catalog/tx_parallel_serializer.json"
            }
          ]
        },
        {
          "id": "20261107T053024Z_af9d6482ca",
          "module": "tx.capture",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T05:30:24.304205+00:00",
          "title": "guard映射时序：SS不足，驱动对照未闭合",
          "phase": "validation",
          "problem": "RTL事件模型没有实际门延迟，需判断控制在半周期预算下能否驱动捕获数据与标签。",
          "model": "4ns时钟、100ps输入/时钟、50ps不确定度；四个HD库、5/10/20fF；外部建立0.5ns、标签提前1.3ns为待校准预算。",
          "changes": "增加Yosys映射/OpenSTA可行性runner；原网表、strength2/4及独立输出buffer对照，RTL未改，候选未采用。",
          "validation": "集成者独立复跑48组。SS冷10fF基线setup -0.57753ns，buffer后最差转A标签、-0.41694ns；strong4更差。工具警告、cap规则未知、复位排除保留。",
          "conclusion": "先测实际DFF建立保持/输入电容、确定标签消费端，再比较扇出与控制结构；不继续统一加大门。非45PVT/布局后签核。",
          "attachments": [
            {
              "title": "tx-ingress-timing.md",
              "path": "docs/work_packages/reviews/tx-ingress-timing.md"
            },
            {
              "title": "tx_ingress_timing_feasibility.png",
              "path": "docs/figures/tx/ingress/tx_ingress_timing_feasibility.png"
            },
            {
              "title": "tx_ingress_timing.json",
              "path": "results/catalog/tx_ingress_timing.json"
            }
          ]
        },
        {
          "id": "20261107T054137Z_b9133c5a73",
          "module": "tx.capture",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T05:41:37.552222+00:00",
          "title": "FS热角完整TX失败：低裕量集中半字边界",
          "phase": "validation",
          "problem": "TT过不能代替压力角，需在同电路、固定位序下检查FS低压热角。",
          "model": "按已登记FS负载时钟生成RTL输入，独立重算逐位/眼图/位映射，并按bit槽分解裕量和残差。",
          "changes": "电路和相位未调；完成FS120ns及两例已有raw的逐槽诊断，保留失败。",
          "validation": "FS22有效字的捕获/保持/计数正确，但串化器0.517mV、0.33258UI、额外交越2；远端marker48错。最差payload位232/slot8，其余载荷槽111–133mV，变化输入在选通前约1.1ns已到din_b。",
          "conclusion": "优先补观测转换器/逐级树，检查B半字及marker帧边界首次劣化位置；不能以零payload误码或纯延时位序把失败改通过。PLL原生/全角/MC/噪声仍未资格化。",
          "attachments": [
            {
              "title": "tx_parallel_serializer.md",
              "path": "docs/design/tx_parallel_serializer.md"
            },
            {
              "title": "tx_parallel_integration.md",
              "path": "docs/history/tx_parallel_integration.md"
            },
            {
              "title": "tx_parallel_serializer_eye.png",
              "path": "docs/figures/tx/ingress/tx_parallel_serializer_eye.png"
            },
            {
              "title": "tx_parallel_diagnostic.json",
              "path": "results/catalog/tx_parallel_diagnostic.json"
            }
          ]
        }
      ]
    },
    {
      "id": "tx.clocking",
      "parent": "tx",
      "name": "选择时钟分发",
      "key": "T02",
      "subtitle": "同步计数器与 2G 延迟复制",
      "state": "改进验证中",
      "summary": "同步计数器v3结构保留；extra2g由1→3改善末级建立。局部校准后完整TX的TT/FS热/SS冷三点眼图、位序、捕获和计数满足；SS冷角动态已通过眼图门槛，摆幅/45点/统计未闭合。",
      "facts": {
        "设计": "v3 同步结构",
        "PVT": "旧回放15/静态8；新入口extra3 TT/FS/SS冷三点眼图满足",
        "失配": "路径局部 MC 待补",
        "噪声": "附加抖动待测"
      },
      "boundary": {
        "inputs": [
          "2 GHz CML 抽出、局部偏置"
        ],
        "outputs": [
          "250M / 500M / 1G / 2G 选择时钟，加载为真实串化器"
        ],
        "assumptions": [
          "相位位置和波形质量均需匹配；源记录必须符合输入负载签名。"
        ]
      },
      "planning": {
        "question": "为什么固定延迟不能同时适配各 PVT？",
        "model": "路径结构比较：buffer、分频 clk→q、重定时和复制单元的漂移分解。",
        "parameters": "计数器/复制的同构时钟路径，隔离和对中级数。",
        "verification": "计数序列、相对时序、眼图与位映射分别检查。"
      },
      "references": [
        {
          "title": "分发设计",
          "path": "docs/design/tx_clock_distribution.md"
        },
        {
          "title": "结构模型",
          "path": "analog/tx/clock_distribution/theory/clock_structures.py"
        },
        {
          "title": "内部CML摆幅与尺寸约束",
          "path": "docs/design/tx_cml_amplitude.md"
        }
      ],
      "iterations": [
        {
          "id": "tx-clock-v3",
          "title": "从独立分频路径改为同步计数器",
          "date": "2026-10-31",
          "phase": "validation",
          "problem": "不同分频级数把工艺、温度延迟留在各路相对位置中。",
          "model": "balance 对六种时钟构造比较，拟合单元漂移后选择同构 clk→q 路径。",
          "changes": "三位同步计数器共用时钟，2G 加复制单元，各路隔离后对中。",
          "validation": "15 个回放 V/T 点按原始位序满足眼图门槛；原生真实偏置静态 8 个完整点正确计数。",
          "conclusion": "作为时钟分发的结构改进，继续补实际发数边界与局部统计。",
          "attachments": [
            {
              "title": "结构比较",
              "path": "analog/tx/clock_distribution/theory/clock_structures.py"
            },
            {
              "title": "v3 电路生成器",
              "path": "analog/tx/serializer/tb/clock_replay/variants/dist_v3.py"
            },
            {
              "title": "原生静态结果",
              "path": "docs/figures/tx/clock_distribution/tx_v3_native_r5_static_summary.png"
            }
          ]
        },
        {
          "id": "20261107T102821Z_b9a39b64d0",
          "module": "tx.clocking",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T10:28:21.099586+00:00",
          "title": "末级建立不足的选择时钟改进：局部校准与TT/FS完整回归",
          "phase": "validation",
          "problem": "完整TX的FS低压热角在字捕获/保持正确时仍有0.52mV裕量、0.333UI散布及额外交越。",
          "model": "保持输入/负载不变追加内部观测，再登记g3/c2g边界；原样切片校准后比较时移与实际缓冲级。",
          "changes": "2GHz选择路径extra中间缓冲由1增至3；末级MUX/保持尺寸与其余时钟级数不变。",
          "validation": "4基线/20时移点及实际1/2/3级局部比较完成；新边界完整120ns：TT155.675mV/0.03137UI、FS128.293mV/0.08961UI，256载荷、训练/marker/位序、捕获/保持和计数正确。",
          "conclusion": "两点串化眼图门槛恢复，继续扩SS低压冷角。内部摆幅I-17、全45点/源阻抗/噪声/MC和物理guard仍开。",
          "attachments": [
            {
              "title": "tx_final_retime.md",
              "path": "docs/design/tx_final_retime.md"
            },
            {
              "title": "tx_parallel_serializer.md",
              "path": "docs/design/tx_parallel_serializer.md"
            },
            {
              "title": "tx_final_retime_boundary.png",
              "path": "docs/figures/tx/ingress/tx_final_retime_boundary.png"
            },
            {
              "title": "tx_parallel_serializer_eye.png",
              "path": "docs/figures/tx/ingress/tx_parallel_serializer_eye.png"
            },
            {
              "title": "tx_final_retime_characterization.md",
              "path": "docs/history/tx_final_retime_characterization.md"
            }
          ]
        },
        {
          "id": "20261107T145148Z_7c8bb71f17",
          "module": "tx.clocking",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T14:51:48.243431+00:00",
          "title": "extra3扩压力点：SS低压冷角完整动态通过眼图门槛",
          "phase": "validation",
          "problem": "两点时序改善需要在慢冷压力条件确认。",
          "model": "先同负载48ns静态记录字时钟，再登记事件并运行相同Icarus生产者，不拟合输出相位。",
          "changes": "保持extra3及输出WT24/R300，SS1.65V−40°C接完整捕获/树/驱动/RLC16。",
          "validation": "120ns完整；137.612mV/0.03607UI；256载荷、训练/marker、自然位序、捕获保持和计数正确；求解约731s。",
          "conclusion": "三点眼图门槛已满足；SS pad/remote约481/468mV，幅度及全部45PVT/统计仍未闭合。",
          "attachments": [
            {
              "title": "tx_parallel_serializer.md",
              "path": "docs/design/tx_parallel_serializer.md"
            },
            {
              "title": "tx_parallel_serializer.json",
              "path": "docs/data/tx_parallel_serializer.json"
            }
          ]
        },
        {
          "id": "20261107T161235Z_1843ec1550",
          "module": "tx.clocking",
          "date": "2026-11-08",
          "timestamp": "2026-11-07T16:12:35.275091+00:00",
          "title": "完整TX逐节点摆幅定位",
          "phase": "validation",
          "problem": "串化眼图满足仍不能关闭400mVpp内部上限。",
          "model": "完整时钟周期最小幅度与窗口极值分开；数据仅观察上界，共模按时间积分。",
          "changes": "只读既有extra3 TT/FS热/SS冷三组120ns波形，校验来源与捕获/保持/计数后，在40–100ns逐节点归类。",
          "validation": "原c2g约620–748mVpp，其他时钟、计数器、数据树与held亦有超幅；数据下限不评分。",
          "conclusion": "I-17继续打开；按真实扇出逐层校准R/尾流与时序，最终c2g局部修复不能代表全部节点。",
          "attachments": [
            {
              "title": "幅度图",
              "path": "docs/figures/tx/ingress/tx_cml_amplitude_map.png"
            },
            {
              "title": "范围和数据",
              "path": "docs/design/tx_cml_amplitude.md"
            },
            {
              "title": "局部尺寸工作方案",
              "path": "docs/work_packages/deliveries/tx-cml-sizing-next.md"
            }
          ]
        }
      ]
    },
    {
      "id": "tx.serializer",
      "parent": "tx",
      "name": "16:1 串化器",
      "key": "T03",
      "subtitle": "CMOS→CML / 选择树 / 末级重定时",
      "state": "结构已实现",
      "summary": "完整TX的FS异常已定位g3_0与末级A关闭建立不足；保持r2尺寸，2G选择时钟改进后TT/FS/SS冷眼图恢复。",
      "facts": {
        "设计": "r2 结构与尺寸",
        "PVT": "固定边界 45 点",
        "失配": "待做",
        "噪声": "待做"
      },
      "boundary": {
        "inputs": [
          "16 路 CMOS 数据；四路选择时钟及其相对位置"
        ],
        "outputs": [
          "4 Gb/s 差分 CML，加载为输出隔离级"
        ],
        "assumptions": [
          "75 mV / 0.15 UI 测于串化器输出。",
          "长连码交接凹口与孤立位 ISI 需要长码型检查。"
        ]
      },
      "planning": {
        "question": "末级跟踪恢复、电流交接和选择沿怎样影响边沿散布？",
        "model": "时序窗口与单元负载/恢复模型，仿真校准。",
        "parameters": "保持 W40、尾 W144、负载 300 Ω；选择时钟共同路径。",
        "verification": "128 bit 网格、TT/FS 热 1024 bit 记录和内部节点诊断。"
      },
      "references": [
        {
          "title": "串化器设计",
          "path": "docs/design/tx_serializer.md"
        },
        {
          "title": "工作电路",
          "path": "analog/tx/serializer/spice/serializer16_retimed_lowov.spice"
        },
        {
          "title": "内部CML摆幅与尺寸约束",
          "path": "docs/design/tx_cml_amplitude.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "tx.serializer.retime",
      "parent": "tx.serializer",
      "name": "末级重定时",
      "key": "T03.4",
      "subtitle": "g3数据 → 保持/选择 · 2G接口",
      "state": "时序改进验证中",
      "summary": "FS原g3过零晚于A关闭5–6ps；经校准切片/实际级数选择extra2g=3，完整TX的TT/FS/SS冷眼图与位序满足；继续扩压力点。",
      "facts": {
        "设计": "末级尺寸保留，改进2G时钟位置",
        "PVT": "TT/FS/SS冷完整120ns、256载荷；未45点",
        "失配": "尚未纳入",
        "噪声": "尚未纳入"
      },
      "boundary": {
        "inputs": [
          "g3_0/1差分数据，2GHz选择，本地偏置"
        ],
        "outputs": [
          "4Gb/s串化qp/qn，加载实际driver/RLC16"
        ],
        "assumptions": [
          "首级半字A/B与末级锁存器A/B是不同层次；两异常事件均由末级A承载。",
          "理想记录电压切片须先校准；不保留上游源阻抗/反馈，不替代完整TX。"
        ]
      },
      "planning": {
        "question": "选择关闭前数据是否充分建立，怎样增加有效建立时间？",
        "model": "实际节点时序与固定前史回放，原样校准后比较时移，再用实际缓冲级校准。",
        "parameters": "末级Wdata40/Whold40；保持尾W144、R300；extra2g=1→3候选。",
        "verification": "4基线/20平移点、实际三种级数已测；完整TT/FS回归通过，继续扩角/统计/噪声。"
      },
      "references": [
        {
          "title": "末级建立与改进",
          "path": "docs/design/tx_final_retime.md"
        },
        {
          "title": "平移允许窗",
          "path": "docs/figures/tx/ingress/tx_final_retime_window.png"
        },
        {
          "title": "实际级数比较",
          "path": "docs/figures/tx/ingress/tx_final_clock_stage_comparison.png"
        }
      ],
      "iterations": [
        {
          "id": "20261107T102821Z_4f8a943296",
          "module": "tx.serializer.retime",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T10:28:21.103578+00:00",
          "title": "末级允许窗与实际关闭沿：切片预测得到完整链确认",
          "phase": "validation",
          "problem": "完整TX的FS低压热角在字捕获/保持正确时仍有0.52mV裕量、0.333UI散布及额外交越。",
          "model": "保持输入/负载不变追加内部观测，再登记g3/c2g边界；原样切片校准后比较时移与实际缓冲级。",
          "changes": "2GHz选择路径extra中间缓冲由1增至3；末级MUX/保持尺寸与其余时钟级数不变。",
          "validation": "4基线/20时移点及实际1/2/3级局部比较完成；新边界完整120ns：TT155.675mV/0.03137UI、FS128.293mV/0.08961UI，256载荷、训练/marker/位序、捕获/保持和计数正确。",
          "conclusion": "两点串化眼图门槛恢复，继续扩SS低压冷角。内部摆幅I-17、全45点/源阻抗/噪声/MC和物理guard仍开。",
          "attachments": [
            {
              "title": "tx_final_retime.md",
              "path": "docs/design/tx_final_retime.md"
            },
            {
              "title": "tx_parallel_serializer.md",
              "path": "docs/design/tx_parallel_serializer.md"
            },
            {
              "title": "tx_final_retime_boundary.png",
              "path": "docs/figures/tx/ingress/tx_final_retime_boundary.png"
            },
            {
              "title": "tx_parallel_serializer_eye.png",
              "path": "docs/figures/tx/ingress/tx_parallel_serializer_eye.png"
            },
            {
              "title": "tx_final_retime_characterization.md",
              "path": "docs/history/tx_final_retime_characterization.md"
            }
          ]
        }
      ]
    },
    {
      "id": "tx.driver",
      "parent": "tx",
      "name": "线驱动与使能",
      "key": "T04",
      "subtitle": "隔离 / 预驱 / 电流舵输出",
      "state": "结构已实现",
      "summary": "约 8 mA 差分电流舵输出；低阈值使能传输门解决冷角尾偏置建立过慢。",
      "facts": {
        "设计": "r2 使能改进",
        "PVT": "启用 / DC 45 点",
        "失配": "待补",
        "噪声": "供电回流待表征"
      },
      "boundary": {
        "inputs": [
          "串化 CML；tx_en；偏置与独立电源"
        ],
        "outputs": [
          "源端 2×50 Ω，经 pad/封装/AC 进入信道"
        ],
        "assumptions": [
          "外部 100 Ω 不随片内电阻角同比变化；pad/ESD/封装为代理。"
        ]
      },
      "planning": {
        "question": "怎样在 SS 冷角及时建立尾电流？",
        "model": "偏置门充电与尾源余量诊断。",
        "parameters": "N-LVT W2、P-LVT W32；输出尾流约 8 mA。",
        "verification": "从禁用态启动、启用电流、关断残流和真实负载波形。"
      },
      "references": [
        {
          "title": "输出级设计",
          "path": "docs/design/tx_output_driver.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "bias.reference",
      "parent": "bias",
      "name": "带隙与 V→I",
      "key": "B01",
      "subtitle": "N=8 / r_ref 5 bit 修调",
      "state": "结构已实现",
      "summary": "电压型带隙抬高误差放大器输入共模，V→I 采用单级 OTA，主误差由修 r_ref 处理。",
      "facts": {
        "设计": "拓扑与补偿已有",
        "PVT": "135 点 DC / 上电",
        "失配": "200 样本；PNP 无失配项",
        "噪声": "供电响应已表征"
      },
      "boundary": {
        "inputs": [
          "电源斜坡、trim[4:0]、分配器栅负载"
        ],
        "outputs": [
          "vbg、约 10 µA 参考及 PMOS 分配控制 vgi"
        ],
        "assumptions": [
          "上电验证使用 1 µs 电源斜坡；带分配/去耦最慢约 16.3 µs。"
        ]
      },
      "planning": {
        "question": "在 1.65 V 冷角满足输入共模和可靠启动，同时保持稳定？",
        "model": "gm/ID 卡、PNP ΔVBE 与电阻温漂、两个反馈环增益。",
        "parameters": "N=8、核心 Miller 6 pF，分配存在时 vgi 外加 2 pF。",
        "verification": "135 点 DC 与上电，MC 分解和配对温漂。"
      },
      "references": [
        {
          "title": "设计与统计",
          "path": "docs/design/bias.md"
        },
        {
          "title": "带隙电路",
          "path": "analog/common/bias/spice/bandgap.spice"
        }
      ],
      "iterations": []
    },
    {
      "id": "bias.distribution",
      "parent": "bias",
      "name": "电流分配与去耦",
      "key": "B02",
      "subtitle": "远距离电流 / 本地栅偏置",
      "state": "结构已实现",
      "summary": "模块本地二极管产生栅压，参考分配保持电流密度。vbg 和 vbias 去耦降低高频供电耦合。",
      "facts": {
        "设计": "模块电流拷贝",
        "PVT": "135 点；PSRR 90 点",
        "失配": "200 样本 × 三温",
        "噪声": "共享参考相关性保留"
      },
      "boundary": {
        "inputs": [
          "vgi、模块电源、支路负载"
        ],
        "outputs": [
          "CML 212.5 µA；CTLE / CP 50 µA 拷贝"
        ],
        "assumptions": [
          "摆幅代理 σ1.6–1.9% 含本地镜、尾管和负载；不等同所有实际节点摆幅。"
        ]
      },
      "planning": {
        "question": "参考去耦与各模块栅负载怎样共同决定速度和噪声？",
        "model": "分配镜的余量 / 失配、vgi 主极点、偏置到 VCO 频率传递。",
        "parameters": "本地 CML 二极管 5/0.5；vbg、vbias 各 5 pF。",
        "verification": "DC、上电、阶跃、PSRR 与逐项 MC。"
      },
      "references": [
        {
          "title": "分配电路",
          "path": "analog/common/bias/spice/bias_dist.spice"
        },
        {
          "title": "偏置设计",
          "path": "docs/design/bias.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "bias.vcm",
      "parent": "bias",
      "name": "RX 共模参考",
      "key": "B03",
      "subtitle": "1.05 V / 单级 OTA 缓冲",
      "state": "结构已实现",
      "summary": "端接共模由独立电压缓冲提供，配合 AC 耦合允许 CTLE 保持足够尾管余量。",
      "facts": {
        "设计": "缓冲已有",
        "PVT": "135 点",
        "失配": "修调后预算约 ±26 mV",
        "噪声": "实际加载待校准"
      },
      "boundary": {
        "inputs": [
          "参考电流、r_ref 修调、电源"
        ],
        "outputs": [
          "RX 端接 1.05 V ±50 mV 目标"
        ],
        "assumptions": [
          "外部 AC 电容的启动充电不能从小电容 DC 表征推断。"
        ]
      },
      "planning": {
        "question": "静态精度与 AC 耦合充电速度怎样分开设计？",
        "model": "参考误差预算、OTA 负载极点和充电电流。",
        "parameters": "1.05 V、5 pF 局部负载；外部 AC 每端 10 nF 为现行代理。",
        "verification": "DC / MC 与独立实际负载启动测试。"
      },
      "references": [
        {
          "title": "vcm 缓冲",
          "path": "docs/design/bias.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "bias.precharge",
      "parent": "bias",
      "name": "LF 预充参考 B2",
      "key": "B04",
      "subtitle": "16 档 / 0.95–1.35 V",
      "state": "结构已实现",
      "summary": "单级 LVT OTA 仅开关尾流，参考拷贝常通以免扰动共享 vgi。",
      "facts": {
        "设计": "B2 与预充门已有",
        "PVT": "405 工况",
        "失配": "专项待补",
        "噪声": "释放 / 漏电已表征"
      },
      "boundary": {
        "inputs": [
          "预充码、en、参考电流、Cf/Ci 实际负载"
        ],
        "outputs": [
          "预充参考，驱动 LF ctrl 和 z"
        ],
        "assumptions": [
          "到 10 mV ≤360 ns；44 点最终误差超过 ±10 mV，均在 ±40 mV 内。"
        ]
      },
      "planning": {
        "question": "预充目标与环路可捕获初值如何衔接？",
        "model": "OTA 充电 / 负载极点、预充门余量、分层 PLL 初值捕获。",
        "parameters": "300 µA 尾流、16 档电阻串、512 ns 预充窗口。",
        "verification": "405 点建立与误差、释放扰动、关断漏电。"
      },
      "references": [
        {
          "title": "B2 设计",
          "path": "docs/design/bias.md"
        },
        {
          "title": "B2 电路",
          "path": "analog/common/bias/spice/bias_dist.spice"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.vco",
      "parent": "pll",
      "name": "VCO 与粗调阵列",
      "key": "C01",
      "subtitle": "四级 CML 环振 / r5 / 4 bit",
      "state": "工作区改进",
      "summary": "r5减损耗/4bit量程保留；补测FF/FS共同码后45组均有三温静态交点，原42统计来自候选码缺项。工作点/噪声/环路仍待匹配。",
      "facts": {
        "设计": "r5 减损耗 / 4 bit 阵列",
        "PVT": "135条件；45组三温共同码静态覆盖",
        "失配": "局部 MC 待补",
        "噪声": "7 压力点 ISF"
      },
      "boundary": {
        "inputs": [
          "Vctrl、粗调 cfg、局部偏置、四路对称抽出负载"
        ],
        "outputs": [
          "约 2 GHz 四对差分 / 八相"
        ],
        "assumptions": [
          "2 GHz 交点与 Kvco 由离散仿真点插值。",
          "当前码表和 3 bit 噪声工作点分开记录。"
        ]
      },
      "planning": {
        "question": "损耗、量程、Kvco 和 CP 控制范围如何共同选点？",
        "model": "1/f 对码拟合用于选点；仿真确认工作区；ISF 加环路传递形成抖动预算。",
        "parameters": "开关 W5；变容 4.5×4 指；15 个半单元；0.85 V 到 CP 上沿。",
        "verification": "原42组＋12点补测三组后45/45组三温有共同码；实际B2/CP-LF、hl/lh与动态未验证。"
      },
      "references": [
        {
          "title": "VCO 设计",
          "path": "docs/design/pll_vco.md"
        },
        {
          "title": "工作区模型与验证",
          "path": "analog/pll/vco/tb/tuning/workmap.py"
        }
      ],
      "iterations": [
        {
          "id": "vco-r5-loss",
          "title": "降低节点损耗，扩为 4 bit 工作区",
          "date": "2026-11-06",
          "phase": "validation",
          "problem": "慢热角节点损耗使摆幅和相噪不足，原 3 bit 在部分角有调谐缺口。",
          "model": "分析变容/开关等效损耗；以 1/f–码拟合筛点，CP 窗口约束 Vctrl。",
          "changes": "开关 W1→5；变容单指改 4.5×4；去固定 MIM；15 个半单元阵列。",
          "validation": "4 bit工作区135条件可达2 GHz；42/45组固定码全温已确认，其余3组覆盖不足，不能判无解。",
          "conclusion": "工作区改进成立；按所选码校准 Kvco 与噪声，供环路选参。",
          "attachments": [
            {
              "title": "工作区 / Kvco",
              "path": "docs/figures/clocking/vco/vco_r5_4b_code_kvco_grid.png"
            },
            {
              "title": "控制范围比较",
              "path": "docs/figures/clocking/vco/vco_r5_3b_4b_control_windows.png"
            },
            {
              "title": "工作区脚本",
              "path": "analog/pll/vco/tb/tuning/workmap.py"
            }
          ]
        },
        {
          "id": "20261107T103653Z_3372acc0db",
          "module": "pll.vco",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T10:36:53.575340+00:00",
          "title": "补测共同码：三温静态覆盖42组→45组",
          "phase": "validation",
          "problem": "旧extend把缺少共同候选码的高温/CP上沿测点读成仅42/45组固定码覆盖。",
          "model": "审查筛点与np.interp端点钳位；先补候选整数码，不先增加码位。",
          "changes": "固定原r5四位阵列/真实偏置/PDK R和负载，FF1.95Rtt code7、FF Rll code12、FS Rll code7各补4高温控制电压点。",
          "validation": "12点完整24ns，新3deck无执行/日志失败；与旧24个冷/常温点的物理边界一致，9条温度曲线均在实际夹区跨2GHz。",
          "conclusion": "原42组加补测3组为45/45组三温静态共同码；不同VDD可不同码。精确落点、实际CP/LF/B2、闭环/启动/噪声/失配仍开。",
          "attachments": [
            {
              "title": "pll_vco.md",
              "path": "docs/design/pll_vco.md"
            },
            {
              "title": "vco_fixed_code_temperature.png",
              "path": "docs/figures/clocking/vco/vco_fixed_code_temperature.png"
            },
            {
              "title": "vco_cp_edge_fill.json",
              "path": "docs/data/vco_cp_edge_fill.json"
            },
            {
              "title": "vco_fixed_code_coverage.md",
              "path": "docs/history/vco_fixed_code_coverage.md"
            }
          ]
        }
      ]
    },
    {
      "id": "pll.extraction",
      "parent": "pll",
      "name": "多相抽出与负载",
      "key": "C02",
      "subtitle": "四路 buffer / 供电 dummy",
      "state": "结构已实现",
      "summary": "四相以相同抽出和下游结构维持环振负载对称，后续低功耗修改单独验证边界。",
      "facts": {
        "设计": "对称抽出已有",
        "PVT": "原生选定工作点",
        "失配": "负载 / 相位待补",
        "噪声": "附加路径待校准"
      },
      "boundary": {
        "inputs": [
          "VCO 四对输出、全局偏置"
        ],
        "outputs": [
          "TX 抽头、PI 锚点、分频 / 接收器输入"
        ],
        "assumptions": [
          "3 路 dummy 参与负载对称，删减前应更新负载签名。"
        ]
      },
      "planning": {
        "question": "实际扇出和电平怎样反馈到 VCO 相位与频率？",
        "model": "静态输入导纳、单元负载和多相相位间隔。",
        "parameters": "每相抽出 buffer、残余布线 0.5 fF、实际 PI 路数。",
        "verification": "小负载扰动和多相间距，再决定需要的联合仿真。"
      },
      "references": [
        {
          "title": "抽出策略",
          "path": "config/clock_extraction.toml"
        },
        {
          "title": "r5 前端",
          "path": "analog/pll/top/spice/clock_frontend_r5.spice"
        }
      ],
      "iterations": [
        {
          "id": "20261106T153148Z_d03c2df1f3",
          "module": "pll.extraction",
          "date": "2026-11-06",
          "timestamp": "2026-11-06T15:31:48.337111+00:00",
          "title": "FF冷角分层定位与偏置就绪工作态验证",
          "phase": "validation",
          "problem": "FF/1.95V/−40°C的ll/hh原生联合测试卡在工作点，尚无有效波形。需要区分本地电路功能与模型展开、DC及数值初始化。",
          "model": "先分VCO+四缓冲、实际接收器加载、单÷8，再本地完整前端。用同PVT小模块的DC表组成近似初始电压，验证明确的偏置就绪边界；与真实上电分开。",
          "changes": "新增有界1ns冒烟/24ns局部bench与按输入身份续跑。初始状态登记pll_r5_cold_prebiased_state_v1，按完整消费电路哈希、码/Vctrl及初值文件检查。原PDK和器件尺寸未改；等价log(cosh)测试未解决DC，未采用模型替换。",
          "validation": "ll/hh本地完整前端分别1.989062/1.988507GHz，三级分频及四路全速CMOS/四路反馈共11项功能检查均满足。小模块DC与24ns瞬态完整。全速CMOS峰值约2.022V，器件应力仍待核对。",
          "conclusion": "已有可复核的工作态测试路径；自动DC、真实上电及原TX联合两个缺点仍开。边界不含TX/PFD/CP/LF，也不是闭环、失配或噪声验收。下一步恢复受影响接口并推进实际字入口与环路选参。",
          "attachments": [
            {
              "title": "分层诊断与边界",
              "path": "docs/history/pll_cold_convergence.md"
            },
            {
              "title": "冷角波形",
              "path": "docs/figures/clocking/pll/r5_cold_frontend_isolation.png"
            },
            {
              "title": "局部测试入口",
              "path": "analog/pll/top/tb/convergence/probe.py"
            },
            {
              "title": "数据快照",
              "path": "docs/data/pll_cold_isolation.json"
            },
            {
              "title": "边界登记",
              "path": "config/boundary_conditions.json"
            },
            {
              "title": "版图前推进",
              "path": "docs/status/prelayout_plan.md"
            }
          ]
        }
      ]
    },
    {
      "id": "pll.divider",
      "parent": "pll",
      "name": "CML ÷8 与共用 ÷2",
      "key": "C03",
      "subtitle": "低过驱锁存器 / 级间 buffer",
      "state": "尺寸改进",
      "summary": "保持管尺寸按输入频率确定。首级改 W40 恢复高频再生，后两级保留 W80 以适应较慢输入。",
      "facts": {
        "设计": "首级 W40 / 后级 W80",
        "PVT": "hh / ll 各 45 点",
        "失配": "待补",
        "噪声": "待表征"
      },
      "boundary": {
        "inputs": [
          "标准 2 GHz CML 输入，含实际共模/摆幅/斜率"
        ],
        "outputs": [
          "1G / 500M / 250M 差分与 250 MHz 反馈"
        ],
        "assumptions": [
          "再生频率与输入频率相配；仅有输出摆幅不能证明正确分频。"
        ]
      },
      "planning": {
        "question": "保持管、时钟幅度与共模的可行区在哪里？",
        "model": "单元 f_SO / 再生与电流转向模型，画共模×摆幅可行区。",
        "parameters": "首级保持 W40、尾 W72、600 Ω；后级 W80。",
        "verification": "真实偏置 / PDK R 的单元地图与 ÷8 频率、反馈核对。"
      },
      "references": [
        {
          "title": "分频设计",
          "path": "docs/design/pll_divider.md"
        },
        {
          "title": "单元可行区入口",
          "path": "analog/pll/divider/tb/div2_map/run.py"
        }
      ],
      "iterations": [
        {
          "id": "divider-hold40",
          "title": "按高频再生需求减小首级保持管",
          "date": "2026-11-06",
          "phase": "validation",
          "problem": "旧 W80 为低频模式选择，在 hh 热角 2 GHz 输入下输出再生不足。",
          "model": "先测自激频率与共模 / 摆幅可行区，区分时钟转向和再生限制。",
          "changes": "首级与 RX 读出 ÷2 保持 W80→40，后两级保留 W80。",
          "validation": "PLL ÷8 hh/ll 各45点分频正确；RX 型单元90点通过。",
          "conclusion": "尺寸按各级频率选择，单元结果再用于局部链路回归。",
          "attachments": [
            {
              "title": "分频器设计依据",
              "path": "docs/design/pll_divider.md"
            },
            {
              "title": "单元可行区图",
              "path": "docs/figures/clocking/dividers/div2_w20_clock_feasible_region.png"
            }
          ]
        }
      ]
    },
    {
      "id": "pll.receivers",
      "parent": "pll",
      "name": "CML→CMOS 接收器",
      "subtitle": "反馈转换与全速转换分开",
      "state": "结构已实现",
      "summary": "250 MHz 反馈与 2 GHz 全速输出使用不同尺寸的时钟接收器。静态 RX 数据转换器归属 RX 读出。",
      "facts": {
        "设计": "反馈 / 全速两种尺寸",
        "PVT": "标准边界 45 点",
        "失配": "待补",
        "噪声": "附加抖动待补"
      },
      "boundary": {
        "inputs": [
          "CML 共模、幅度与频率；CMOS 输出负载"
        ],
        "outputs": [
          "CMOS 时钟，恢复级带记忆"
        ],
        "assumptions": [
          "停钟保持不等于静态数据转换，不能把全速时钟接收器用于任意数据。"
        ]
      },
      "references": [
        {
          "title": "接收器设计",
          "path": "docs/design/clock_receiver.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.loop",
      "parent": "pll",
      "name": "鉴相与环路",
      "subtitle": "PFD → CP → LF → Vctrl",
      "state": "集成已有 / 参数迭代",
      "summary": "实际 PFD/CP/LF 已连接于 PLL 顶层。实测 VCO plant 与线性模型用于规划新 Kvco 下的环路参数。",
      "facts": {
        "设计": "电路与闭环顶层已有",
        "PVT": "分层 4 工况 × 3 初值",
        "失配": "CP 局部 MC 待补",
        "噪声": "k2 / 3 / 4 模型比较"
      },
      "boundary": {
        "inputs": [
          "ref/fb 相位差；CP 偏置；VCO 逐角曲线与输出负载"
        ],
        "outputs": [
          "Vctrl；有效带宽、相位裕量和参考纹波"
        ],
        "assumptions": [
          "行为 / 分层模型用来指导参数，不代替所有器件现象。"
        ]
      },
      "planning": {
        "question": "新 Kvco 下怎样兼顾抖动、稳定性、CP 电荷与预充？",
        "model": "逐角 VCO plant + 实际 CP/LF；线性噪声与延迟敏感性分析。",
        "parameters": "允许独立优化 Icp、Rz、Ci/Cf；不要只按 k 比例放大。",
        "verification": "CP 电荷、分层捕获与短原生接回分级验证。"
      },
      "references": [
        {
          "title": "环路设计",
          "path": "docs/design/pll_loop.md"
        },
        {
          "title": "模型与耦合分析",
          "path": "verification/design_coupling_review.py"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.startup",
      "parent": "pll",
      "name": "预充与启动监督",
      "key": "C09",
      "subtitle": "双节点预充 / 门控 / 状态机",
      "state": "电路与 RTL 已有",
      "summary": "PLL 启动顶层和监督 RTL 已有，ready 与质量测量由模块接口输入；B2 参考作为 Bias 子模块提供。",
      "facts": {
        "设计": "启动核心 / 监督 RTL 已有",
        "PVT": "局部预充与分层捕获",
        "失配": "按支路预算",
        "噪声": "释放 / 漏电表征"
      },
      "boundary": {
        "inputs": [
          "bias_ready、pre_ref_ready、频率/相位测量结果、start/reset"
        ],
        "outputs": [
          "pre_en、CP enable、PFD reset、locked / fault"
        ],
        "assumptions": [
          "监督器不自动产生频率计、TDC 或模拟 ready 检测。"
        ]
      },
      "planning": {
        "question": "偏置建立和捕获需要什么时序预算？",
        "model": "状态机周期、B2 充电和分层初值捕获配合。",
        "parameters": "128 参考周期预充、2 周期 GAP、2 周期 FLUSH。",
        "verification": "RTL 默认周期 / 异常输入，模拟释放与捕获。"
      },
      "references": [
        {
          "title": "启动监督器",
          "path": "digital/pll/README.md"
        },
        {
          "title": "启动电路顶层",
          "path": "analog/pll/top/spice/pll_balanced_startup_core.spice"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.coarse",
      "parent": "pll",
      "name": "粗调搜索与切码控制",
      "key": "C10",
      "subtitle": "阵列码接口已有 / 自动搜索待做",
      "state": "策略规划",
      "summary": "VCO 粗调码和阵列已在 PLL 中；自动搜索、温度漂移重校与无扰切码控制仍是独立控制任务。",
      "facts": {
        "设计": "码接口已有，控制器待做",
        "PVT": "工作区支撑选码",
        "失配": "码边界统计待补",
        "噪声": "切码扰动待测"
      },
      "boundary": {
        "inputs": [
          "频率误差、Vctrl 上下限、已有粗码"
        ],
        "outputs": [
          "阵列粗码与冻结 / 越界状态"
        ],
        "assumptions": [
          "码增大频率降低，Kvco 为正；二进制多位跳码需专门处理。"
        ]
      },
      "planning": {
        "question": "一个码能覆盖多大温区，什么时候重新粗搜？",
        "model": "135 条件可达码集合与全温交集。",
        "parameters": "4 bit 码0–15、迟滞、确认次数、保持时间与端点策略。",
        "verification": "先静态覆盖和捕获，再受控切码。"
      },
      "references": [
        {
          "title": "粗调政策",
          "path": "docs/history/vco_coarse_calibration.md"
        },
        {
          "title": "工作区",
          "path": "docs/design/pll_vco.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.receivers.feedback",
      "parent": "pll.receivers",
      "name": "反馈时钟转换",
      "key": "C04",
      "subtitle": "250 MHz / 保留 pvt_candidate 尺寸",
      "state": "结构已实现",
      "summary": "在 ÷8 后转换为 PFD 的 250 MHz CMOS 反馈。",
      "facts": {
        "设计": "反馈接收器已有",
        "PVT": "标准 45 与 hh/ll 分频回归",
        "失配": "待补",
        "噪声": "待表征"
      },
      "boundary": {
        "inputs": [
          "÷8 CML 抽头及负载"
        ],
        "outputs": [
          "PFD 反馈 CMOS"
        ],
        "assumptions": [
          "与全速 r4 尺寸分开。"
        ]
      },
      "references": [
        {
          "title": "反馈电路",
          "path": "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.receivers.fullrate",
      "parent": "pll.receivers",
      "name": "全速时钟转换",
      "key": "C05",
      "subtitle": "r4 big / 2 GHz",
      "state": "角点改进已验证",
      "summary": "增大差分级输入、镜像负载与预驱动能力，解决 SS 冷角上拉与翻转失败。",
      "facts": {
        "设计": "r4 尺寸改进",
        "PVT": "标准 45 / 原生 5 点",
        "失配": "待补",
        "噪声": "附加抖动待测"
      },
      "boundary": {
        "inputs": [
          "抽出后的 2 GHz CML；20 fF CMOS 负载边界"
        ],
        "outputs": [
          "恢复的互补 CMOS 时钟"
        ],
        "assumptions": [
          "SS 热角幅度余量约110 mV；过冲约2.05 V需核对器件端电压。"
        ]
      },
      "references": [
        {
          "title": "r4 接收器",
          "path": "docs/design/clock_receiver.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.loop.pfd",
      "parent": "pll.loop",
      "name": "PFD",
      "key": "C06",
      "subtitle": "三态 CMOS / 复位脉宽",
      "state": "结构已实现",
      "summary": "实际 CMOS 鉴相器通过公共复位产生 UP/DN，有限脉宽进入 CP 电荷行为。",
      "facts": {
        "设计": "电路已有",
        "PVT": "45×三相差电荷方向",
        "失配": "近零 / 随机项待补",
        "噪声": "鉴相噪声待细化"
      },
      "boundary": {
        "inputs": [
          "250 MHz ref/fb、rst_b"
        ],
        "outputs": [
          "高有效 UP / DN 脉冲"
        ],
        "assumptions": [
          "±200/0 ps 三点不能证明近零无死区。"
        ]
      },
      "references": [
        {
          "title": "PFD / CP 环路",
          "path": "docs/design/pll_loop.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.loop.cp",
      "parent": "pll.loop",
      "name": "Charge pump",
      "key": "C07",
      "subtitle": "电流匹配 / 合规窗口 / 电荷",
      "state": "参数改进规划",
      "summary": "长沟道镜与串联开关构成实际 CP。DC 窗口、上下拉差别和有限脉宽电荷分别验证。",
      "facts": {
        "设计": "50 µA 实现；k 比较中",
        "PVT": "DC 窗口 135 点",
        "失配": "随机 MC 待补",
        "噪声": "电流 / 脉宽模型待细化"
      },
      "boundary": {
        "inputs": [
          "UP / DN、有使能版本、vbn/vbp、Vctrl"
        ],
        "outputs": [
          "滤波器输入电荷与电流"
        ],
        "assumptions": [
          "约11% UP/DN 差别是确定性角点结果，不是局部随机失配统计。"
        ]
      },
      "planning": {
        "question": "增大 Icp 后如何保持电荷、输出余量与参考杂散？",
        "model": "DC 电流下垂窗口、脉冲电荷与实际 VCO plant。",
        "parameters": "Icp、开关与驱动尺寸、电流密度、输出阻抗。",
        "verification": "窗口135点、有限脉宽/近零电荷，再与LF联合。"
      },
      "references": [
        {
          "title": "CP 窗口",
          "path": "docs/figures/clocking/pll/charge_pump/cp_real_bias_dc_windows.png"
        },
        {
          "title": "环路设计",
          "path": "docs/design/pll_loop.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "pll.loop.filter",
      "parent": "pll.loop",
      "name": "Loop filter",
      "key": "C08",
      "subtitle": "Rz / Ci / Cf / 双节点预充",
      "state": "参数改进规划",
      "summary": "已有无源滤波器和预充电路；物理 poly/MIM 实现有表征，环路参数按 Kvco 和噪声联合选择。",
      "facts": {
        "设计": "6.5k / 40p + 2p 已实现",
        "PVT": "无源角与分层捕获",
        "失配": "容差 / 统计待补",
        "噪声": "带宽与供电抵消分析"
      },
      "boundary": {
        "inputs": [
          "CP 电荷、预充参考 / 使能、供电纹波"
        ],
        "outputs": [
          "Vctrl 与积分节点 z"
        ],
        "assumptions": [
          "接 VDD 的电容比例约0.69有20 MHz单音依据，宽带效果按模型和电路分别验证。"
        ]
      },
      "planning": {
        "question": "带宽、稳定性、面积和供电耦合的共同可行区？",
        "model": "线性环路 / 延迟敏感性，配合实际CP分层捕获。",
        "parameters": "Rz、Ci/Cf、Icp 与电容参考端。",
        "verification": "k2/3/4比较，逐角plant校准，选择关键原生点。"
      },
      "references": [
        {
          "title": "环路定参",
          "path": "docs/design/pll_loop.md"
        },
        {
          "title": "联合模型比较",
          "path": "verification/design_coupling_review.py"
        }
      ],
      "iterations": []
    },
    {
      "id": "rx.frontend",
      "parent": "rx",
      "name": "端接与 CTLE",
      "key": "R01",
      "subtitle": "vcm 1.05 V / C2 默认 EQ3",
      "state": "结构已实现",
      "summary": "提高输入共模恢复慢角尾管余量，四档 RC 退化提供可控峰化。",
      "facts": {
        "设计": "四档 CTLE 已有",
        "PVT": "独立 45×4档 / 窗口135",
        "失配": "TT MC200，σ6.1 mV",
        "噪声": "联合噪声待补"
      },
      "boundary": {
        "inputs": [
          "C2 差分远端；2×50 Ω到vcm；EQ与偏置"
        ],
        "outputs": [
          "采样器输入 CML，输出共模随电源"
        ],
        "assumptions": [
          "独立 AC/DC 的理想边界与实际链路边界分开。"
        ]
      },
      "planning": {
        "question": "输入共模如何影响尾管余量和峰化？",
        "model": "工作点共模可行区、gm/RC 零极点与脉冲/眼图。",
        "parameters": "vcm1.05 V、600 Ω退化/负载、200/400 fF档位。",
        "verification": "45×4档、C2名义/弱TX、真实加载对照。"
      },
      "references": [
        {
          "title": "前端设计",
          "path": "docs/design/rx_frontend.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "rx.pi",
      "parent": "rx",
      "name": "相位插值器 PI",
      "key": "R02",
      "subtitle": "64 码 / cmix 120 fF",
      "state": "尺寸改进",
      "summary": "相邻相位间以8个电流单位插值，数据/边沿两路差90°；减小混合电容改善慢热角时钟幅度。",
      "facts": {
        "设计": "64码 / 120f",
        "PVT": "6压力角×hh/ll×64码",
        "失配": "单位误差传播模型",
        "噪声": "附加相位噪声待测"
      },
      "boundary": {
        "inputs": [
          "四对八相锚点、one-hot/温度计控制、局部偏置"
        ],
        "outputs": [
          "数据 / 边沿两对差分，形成D0/E0/D1/E1"
        ],
        "assumptions": [
          "原生锚点负载与理想相关锚点表征分开；控制按受保护±1步。"
        ]
      },
      "planning": {
        "question": "线性度、慢角幅度与动态控制的可行范围？",
        "model": "单位误差传播、RC带宽和扇区交接时序。",
        "parameters": "cmix200→120f、8单位、64码、每码7.8125 ps。",
        "verification": "静态64码、压力角、规定回卷与接采样负载。"
      },
      "references": [
        {
          "title": "PI 与采样",
          "path": "docs/design/rx_pi_sampler.md"
        },
        {
          "title": "PI 电路",
          "path": "analog/rx/pi/spice/pi_rotator.spice"
        }
      ],
      "iterations": []
    },
    {
      "id": "rx.sampler",
      "parent": "rx",
      "name": "四相采样与时钟接口",
      "key": "R03",
      "subtitle": "ac_trim / c2 / 辅助修调对",
      "state": "结构改进已验证",
      "summary": "低过驱尾管和 AC 时钟将时钟共模与 PI 输出静态电平解耦；修调辅助对用于消除输入失调。",
      "facts": {
        "设计": "ac_trim / 主尾+8指",
        "PVT": "135 条件窗口",
        "失配": "局部MC / 理想校准96样本",
        "噪声": "孔径 / 亚稳态待表征"
      },
      "boundary": {
        "inputs": [
          "CTLE CML、PI数据/边沿时钟、4路6bit修调码"
        ],
        "outputs": [
          "D0/D1/E0/E1采样；_rk实现另有读出时钟取点"
        ],
        "assumptions": [
          "135窗口：18完整扫描＋117门槛检查，不包含读出负载。",
          "DUT rb50k，短bench rb2k；启动建立时间分别记录。"
        ]
      },
      "planning": {
        "question": "三层堆叠怎样在低压 PVT 下保持尾源与时钟余量？",
        "model": "共模可行区、buffer粗模型、输入失调与修调灵敏度。",
        "parameters": "低过驱尾W72，c2负载600Ω/尾36，AC0.45p，主尾dtail8。",
        "verification": "压力角窗口全扫，其余门槛，单路MC避免共用输入buffer回踢混淆。"
      },
      "references": [
        {
          "title": "采样设计与测量",
          "path": "docs/design/rx_pi_sampler.md"
        },
        {
          "title": "时钟接口规划",
          "path": "analog/rx/sampler/theory/clock_interface_plan.py"
        }
      ],
      "iterations": []
    },
    {
      "id": "rx.readout",
      "parent": "rx",
      "name": "物理读出与 deser16",
      "key": "R04",
      "subtitle": "CML 1:2 → 匹配转换 → CMOS 1:4",
      "state": "结构已实现 / 角点迭代",
      "summary": "先在 CML 域分路降低每路数据率，再匹配数据与时钟转换延迟；物理字寄存器和 Johnson 选通输出32个样本及w。",
      "facts": {
        "设计": "物理字路径已有",
        "PVT": "旧边界45；W40的FS冷hh数值缺失、FF冷hh未见正式运行",
        "失配": "读出局部MC待补",
        "噪声": "未做；保持/偏斜仅确定性预算"
      },
      "boundary": {
        "inputs": [
          "四路CML采样、_rk读出时钟"
        ],
        "outputs": [
          "16数据＋16边沿、恢复字时钟 w≈250 MHz"
        ],
        "assumptions": [
          "先验证字内连续位映射，再检查数据/确定边沿。",
          "当前÷2保持W40；旧45点报告称W80，历史include无快照，尺寸不可由当前源码追认。"
        ]
      },
      "planning": {
        "question": "怎样避免2GHz CMOS转换路径与数据延迟漂移不一致？",
        "model": "readout_deser_plan逐位映射与建立保持规划，DFF单元卡校准。",
        "parameters": "CML÷2 / 1:2、匹配静态转换、CMOS1:4、Johnson选通。",
        "verification": "旧45点逐位/位映射与短PI动态；当前W40按接口回归。FF额外五次旧数值失败均W80。"
      },
      "references": [
        {
          "title": "读出设计",
          "path": "docs/design/rx_pi_sampler.md"
        },
        {
          "title": "行为时序规划",
          "path": "analog/rx/sampler/theory/readout_deser_plan.py"
        },
        {
          "title": "读出电路",
          "path": "analog/rx/sampler/spice/rx_readout_deser16.spice"
        },
        {
          "title": "冷角实际尝试与数值分层",
          "path": "docs/work_packages/deliveries/rx-cold-readout-diagnostic.md"
        }
      ],
      "iterations": [
        {
          "id": "rx-physical-word",
          "title": "先 CML 分路，再匹配转换与物理字捕获",
          "date": "2026-11-02",
          "phase": "validation",
          "problem": "2GHz直接转CMOS后，数据和时钟路径组成不同，固定对中无法适应角点。",
          "model": "DFF单元卡和逐路径时序规划；仿真前检查16位是否构成连续窗口。",
          "changes": "CML1:2分路＋匹配静态转换＋CMOS1:4/Johnson字选通。",
          "validation": "旧边界45点逐位与位映射正确；TT物理短闭环跨扇区/回卷正确。",
          "conclusion": "物理字读出结构已有；保持管等角点改进继续挂在该模块。",
          "attachments": [
            {
              "title": "时序与位映射规划",
              "path": "analog/rx/sampler/theory/readout_deser_plan.py"
            },
            {
              "title": "电路实现",
              "path": "analog/rx/sampler/spice/rx_readout_deser16.spice"
            }
          ]
        },
        {
          "id": "20261106T195211Z_02dac8afe8",
          "module": "rx.readout",
          "date": "2026-11-07",
          "timestamp": "2026-11-06T19:52:11.675614+00:00",
          "title": "历史读出尺寸与边界清点：保留未知，修正TT库段分类",
          "phase": "validation",
          "problem": "旧45点与近期W40读出边界混用，历史include动态引用工作区源码，难以复原尺寸。",
          "model": "固定10个目录，沿实际deck/includes追参数与PDK快照，逐raw检查终点与有限性，PRBS结论仅摘录历史summary。",
          "changes": "Terra交叉核查指出3项问题；集成者修复TT/hh库段别名和缺失输入检查契约，补2个回归，收紧历史W80/理想R表述。",
          "validation": "固定集合54计划条件，63正式尝试及1smoke；52输出完整，7完整性失败，5输出缺失。633现有输入身份与6缺失路径保留，指定压力边界7/12格具完整正式输出；不是全仓库覆盖率。",
          "conclusion": "清点交付经review接受，未新增PRBS、噪声或当前全角签核。旧包含电路尺寸保持未知，当前W40单独回归；只有smoke的冷角重试不计正式完成。",
          "attachments": [
            {
              "title": "清点摘要",
              "path": "docs/work_packages/deliveries/WP-003/summary.md"
            },
            {
              "title": "集成者review",
              "path": "docs/work_packages/reviews/WP-003.md"
            }
          ]
        },
        {
          "id": "20261107T150911Z_fb43de4ab8",
          "module": "rx.readout",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T15:09:11.552989+00:00",
          "title": "冷角缺口按真实尺寸与尝试分类",
          "phase": "conclusion",
          "problem": "当前W40缺口与旧W80数值失败混记，容易重复不必要的长全链尝试。",
          "model": "固定WP003十来源外再直接复核五个FF hh历史attempt，按snapshot解析读出div2的whold、日志与实际终点。",
          "changes": "无电路修改；修正文档/模块状态，保留WP003固定审计范围。",
          "validation": "FS W40当前正式2400s超时、smoke初始OP失败，均无完整raw；FF新增五次均W80，两个OP失败、三个超时。未定位历史opsteps20/reltol1e-3的一小时对应deck，保持未知。",
          "conclusion": "不能据旧失败判当前W40功能失败，也不能据缺运行判通过；先真实偏置/采样、读出div2、转换、Johnson分层短probe，再同边界完整回归。",
          "attachments": [
            {
              "title": "rx-cold-readout-diagnostic.md",
              "path": "docs/work_packages/deliveries/rx-cold-readout-diagnostic.md"
            },
            {
              "title": "rx_working_revision.toml",
              "path": "config/rx_working_revision.toml"
            }
          ]
        }
      ]
    },
    {
      "id": "rx.calibration",
      "parent": "rx",
      "name": "失调 DAC 与校准",
      "key": "R05",
      "subtitle": "电压型修调 / 两边沿顺序 SAR",
      "state": "算法与电路已有",
      "summary": "寻找迟滞带的两个边沿取中点，逐路校准以控制共用输入buffer造成的回踢。",
      "facts": {
        "设计": "6bit DAC / 两边沿SAR",
        "PVT": "码阈值45；TT/SS热联调",
        "失配": "理想选码96样本",
        "噪声": "迟滞与残差已分析"
      },
      "boundary": {
        "inputs": [
          "电气空闲输入、cal_start、恢复字时钟"
        ],
        "outputs": [
          "四路6bit修调码、cal_done，之后使能CDR"
        ],
        "assumptions": [
          "理想选码MC、注入失调联调、实际SAR随机样本是三类证据。"
        ]
      },
      "planning": {
        "question": "空闲迟滞为何使单次SAR产生残差？",
        "model": "上下行阈值、温漂配对和DAC码–阈值曲线。",
        "parameters": "电压型辅助对；每次试探先预置；顺序寻找两边沿。",
        "verification": "上升/下降慢斜坡残差、TT/SS注入联调，再少量真实配对样本。"
      },
      "references": [
        {
          "title": "校准与失配",
          "path": "docs/design/rx_pi_sampler.md"
        },
        {
          "title": "校准RTL",
          "path": "digital/rx/rtl/rx_offset_cal.sv"
        }
      ],
      "iterations": [
        {
          "id": "rx-two-edge-sar",
          "title": "单次 SAR 改为两边沿顺序校准",
          "date": "2026-11-04",
          "phase": "validation",
          "problem": "空闲迟滞使单次SAR落在带内任意位置，联调残差约2–3mV。",
          "model": "两向阈值与数据模式阈值核对，区分迟滞和邻路回踢。",
          "changes": "每次试探前预置，分别搜索上下沿，再取中点；四路顺序执行。",
          "validation": "注入联调最大数据模式残差 TT1.22mV、SS热0.33mV。",
          "conclusion": "算法改进已有电路联调依据；实际失配下完整SAR统计继续补。",
          "attachments": [
            {
              "title": "校准RTL",
              "path": "digital/rx/rtl/rx_offset_cal.sv"
            },
            {
              "title": "双向残差核对",
              "path": "analog/rx/sampler/tb/offset_dac/cal_check.py"
            }
          ]
        }
      ]
    },
    {
      "id": "rx.cdr",
      "parent": "rx",
      "name": "映射、投票与数字 CDR",
      "key": "R06",
      "subtitle": "恢复字时钟域 / 独立 PI 跟踪",
      "state": "RTL 与分层闭环已有",
      "summary": "物理字映射成时间顺序的数据/边沿票，二阶环路通过受保护PI步进跟踪频差；训练字确定字边界。",
      "facts": {
        "设计": "RTL与物理字路径已有",
        "PVT": "行为10组100µs / 物理短窗",
        "失配": "由模拟边界模型提供",
        "噪声": "行为扰动 / 孔径模型"
      },
      "boundary": {
        "inputs": [
          "16数据＋16边沿、上一数据位、字时钟w"
        ],
        "outputs": [
          "±1 PI步 / one-hot/温度计控制；对齐字 / 状态"
        ],
        "assumptions": [
          "生产KP8192/KI32；物理快速冒烟KP65536。",
          "行为100µs覆盖频偏，与晶体管短窗口验证互补。"
        ]
      },
      "planning": {
        "question": "控制带宽、保护周期和有限步进率是否支持远端频偏？",
        "model": "实际RTL＋行为采样plant，加入PI曲线、处理延迟与孔径误差。",
        "parameters": "KP1/8、KI1/2048、保护周期、频率限幅、质量窗口。",
        "verification": "±300ppm长时模型；物理短窗验证控制动作、跨扇区和回卷。"
      },
      "references": [
        {
          "title": "数字CDR设计",
          "path": "docs/design/rx_cdr_digital.md"
        },
        {
          "title": "物理混合仿真入口",
          "path": "verification/mixed_signal/README.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "rx.cdc",
      "parent": "rx",
      "name": "系统域 FIFO / CDC",
      "key": "R07",
      "subtitle": "恢复字时钟 → 系统时钟",
      "state": "接口待定义",
      "summary": "恢复字时钟跟随远端ppm，输出到系统域需要明确缓冲、流控或空闲补偿策略。",
      "facts": {
        "设计": "待设计",
        "PVT": "按数字时序方法",
        "失配": "不适用模拟MC",
        "噪声": "关注时钟与CDC假设"
      },
      "boundary": {
        "inputs": [
          "恢复域16bit字、w、数据有效"
        ],
        "outputs": [
          "系统域并行数据与流控"
        ],
        "assumptions": [
          "当前前端/行为CDR结果不预设最终协议或系统时钟政策。"
        ]
      },
      "planning": {
        "question": "两侧长期频差由谁吸收？",
        "model": "FIFO占用、ppm与最大无补偿间隔的离散模型。",
        "parameters": "深度、空闲补偿 / 流控策略、同步器时序。",
        "verification": "数字时序、CDC和溢出/欠载场景。"
      },
      "references": [
        {
          "title": "RX数字接口",
          "path": "docs/design/rx_cdr_digital.md"
        }
      ],
      "iterations": []
    },
    {
      "id": "channel.model",
      "parent": "channel",
      "name": "PCB 与端接模型",
      "key": "X01",
      "subtitle": "RLC16 / C0–C5 / 已登记边界",
      "state": "模型已建立",
      "summary": "模型用于明确源阻抗、传输记忆与接收负载，再把合适边界交给局部接收模块。",
      "facts": {
        "设计": "SPICE / S4P / 脉冲模型",
        "PVT": "模型参数表征",
        "失配": "板线容差待定义",
        "噪声": "无串扰模型"
      },
      "boundary": {
        "inputs": [
          "TX差分电流 / 源阻抗、封装与AC电容"
        ],
        "outputs": [
          "接收端电压及负载响应"
        ],
        "assumptions": [
          "回放前先登记负载签名；不可按最新运行隐式选源。"
        ]
      },
      "planning": {
        "question": "需要保留哪些信道记忆，怎样选择可回放截断边界？",
        "model": "S参数、脉冲响应和有限窗ISI；与实际驱动/CTLE加载对照。",
        "parameters": "C2 6dB、C3挑战、反射、0.1UI偏斜、端接和封装代理。",
        "verification": "AC无源性、脉冲、有限码型与边界负载一致性。"
      },
      "references": [
        {
          "title": "模型设计",
          "path": "docs/design/channel_model.md"
        },
        {
          "title": "模型配置",
          "path": "config/channel_family.toml"
        },
        {
          "title": "边界登记",
          "path": "config/boundary_conditions.json"
        }
      ],
      "iterations": []
    },
    {
      "id": "tx.clocking.output2g",
      "parent": "tx.clocking",
      "name": "2 GHz输出缓冲",
      "key": "T02.1",
      "subtitle": "实际末级扇出 · 幅度/关闭时刻",
      "state": "FS散布失败",
      "summary": "extra3、WT16/R240完整TT/FS的c2g为369/349mVpp，捕获/保持/计数和256bit位序正确；TT眼图满足，FS散布0.18025UI失败，不采用。其他内部超幅仍开。",
      "facts": {
        "设计": "Wn32固定；WT16/R240未采用",
        "PVT": "完整TT/FS两点；FS散布失败，非全角",
        "失配": "未做",
        "噪声": "未做"
      },
      "boundary": {
        "inputs": [
          "extra3末级e3差分、vbias、VDD"
        ],
        "outputs": [
          "c2g差分，加载末级A/B保持和MUX三个跟随器/极"
        ],
        "assumptions": [
          "局部理想r2g/数据/偏置电压省略上游阻抗与反馈。",
          "400mVpp内部上界，200mVpp设计目标/150mVpp硬下限；完整翻转仍须检查。"
        ]
      },
      "planning": {
        "question": "减小尾流和R能否同时满足幅度、共模与数据建立？",
        "model": "I·R粗估排序，实际加载瞬态校准；RC/gm权重尚未拟合。",
        "parameters": "extra3；Wn32；WT/R：24/300、18/240、16/240。",
        "verification": "局部四基线5.56µV；完整120ns独立确认字流及位序；FS散布超过0.15UI，需要减幅后的本地时序/再生校准。"
      },
      "references": [
        {
          "title": "输出联合选参",
          "path": "docs/design/tx_final_retime.md"
        },
        {
          "title": "局部比较图",
          "path": "docs/figures/tx/ingress/tx_final_clock_output_sizing.png"
        },
        {
          "title": "局部数据",
          "path": "docs/data/tx_final_clock_swing.json"
        },
        {
          "title": "完整TX尺寸对照",
          "path": "docs/figures/tx/ingress/tx_clock_output_full_confirmation.png"
        },
        {
          "title": "完整确认数据",
          "path": "docs/data/tx_clock_output_confirmation.json"
        },
        {
          "title": "边沿散布复核",
          "path": "docs/work_packages/deliveries/tx-clock-output-edge-review.md"
        },
        {
          "title": "最差边沿内部波形",
          "path": "docs/figures/tx/ingress/tx_clock_output_edge_detail.png"
        }
      ],
      "iterations": [
        {
          "id": "20261107T104530Z_df31902ea8",
          "module": "tx.clocking.output2g",
          "date": "2026-11-07",
          "timestamp": "2026-11-07T10:45:30.896059+00:00",
          "title": "2GHz输出减幅：W16/R240局部候选",
          "phase": "validation",
          "problem": "extra3恢复时序后c2g仍610–689mVpp，超过内部400上界。",
          "model": "固定Wn/上游负载，以I·R粗估选局部点，校准实际PDK R加载和关闭时刻。",
          "changes": "三条独立extra3数学支路比较输出WT/R24/300、18/240、16/240，未改完整TX工作电路。",
          "validation": "4基线对原extra3八节点误差≤5.56µV；W16/R240四事件c2g344–369mVpp，关闭提前约10–13ps，FS局部输出111/175mV。W18/R240的TT仍415–417mVpp。",
          "conclusion": "W16/R240进入完整链候选；局部样点不替代眼图/位序。I17其他节点、全角、源阻抗、MC/噪声仍开。",
          "attachments": [
            {
              "title": "tx_final_retime.md",
              "path": "docs/design/tx_final_retime.md"
            },
            {
              "title": "tx_final_clock_swing.json",
              "path": "docs/data/tx_final_clock_swing.json"
            },
            {
              "title": "tx_final_clock_output_sizing.png",
              "path": "docs/figures/tx/ingress/tx_final_clock_output_sizing.png"
            }
          ]
        },
        {
          "id": "20261107T161954Z_5be2dfa5b2",
          "module": "tx.clocking.output2g",
          "date": "2026-11-08",
          "timestamp": "2026-11-07T16:19:54.605075+00:00",
          "title": "缩摆幅完整TX：TT通过、FS散布失败",
          "phase": "validation",
          "problem": "局部WT16/R240减幅后，需核对完整字流、位序和所有载荷边沿。",
          "model": "探针与动态源图一致，重新登记字时钟事件、保留原IC。训练相位固定，UI为250ps。",
          "changes": "extra3与数据树不变，2GHz末级尾宽24降至16µm，负载300降至240Ω；TT/FS各120ns。",
          "validation": "c2g约369/349mVpp；捕获、保持、标签、175计数与256bit自然位序正确。TT眼图132.38mV/0.05047UI；FS106.35mV/0.18025UI失败。",
          "conclusion": "尺寸不采用；先校准减幅后的本地时钟、再生和数据相关延迟。其他节点超幅、45PVT、物理guard及统计仍开。",
          "attachments": [
            {
              "title": "完整对照",
              "path": "docs/figures/tx/ingress/tx_clock_output_full_confirmation.png"
            },
            {
              "title": "边界与判定",
              "path": "docs/design/tx_final_retime.md"
            },
            {
              "title": "逐边沿复核",
              "path": "docs/work_packages/deliveries/tx-clock-output-edge-review.md"
            }
          ]
        }
      ]
    }
  ],
  "mode": "standalone"
};
