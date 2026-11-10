# WP-LDO-002：r4 交接与下一步集成

**r4 的局部电路、无源、校准、扩展电源网格和启动结果已可复核；现行 PLL 未改接。** 本包接替 r3 的[WP-LDO-001](WP-LDO-001-waveform-review.md)。主文档为[ldo_r4.md](../design/ldo_r4.md)，当前选择为[ldo_working_revision.toml](../../config/ldo_working_revision.toml)。

## 已完成与边界

- 静态双配置：HV3.0–3.6V启用稳压；旁路时板上Vin/quiet同接合格外供1.65–1.95V，enable0。无串联开关、无运行时切换。
- 参考1MΩ/16pF＋关断隔离/放电；核心关断夹镜像偏置；6bit独立电压修调；物理high_po/MIM。
- 校准1088点；每MOS/RC固定名义校准码后，DC1215点输出1.776–1.815V；AC255点、20MHz最差38.44dB、PM最低71.28°。
- 六压力条件×三独立bench的360µs启动/同模式使能循环/静态旁路，共18条。电阻负载、12pF vgi和1pF尾栅代理，不是实际PLL。
- 独立尾偏置1MΩ/16pF候选，三个真实gate AC边界；1MHz改善41–44dB；尚未插入当前PLL。
- 六条件输出/尾偏置共18条纯DC噪声谱；逐次pass电流一致，1k–199.5MHz。没有完整慢节点逐点认证或PLL抖动结论。
- quiet额外电容两边界扫描；1nF时最差PM35.85°，不能任意挂外部去耦。100pF端点另补MOS五角×RC五段共425条DC/AC，最差PM65.07°；电容区间、ESR/真实引脚和启动仍开。

## 证据清单

[ldo_r4_evidence.json](../../config/ldo_r4_evidence.json)锁定九份输入summary，禁止按最新目录替换。发布后的[数据](../data/ldo_r4.json)记录输入summary SHA、cell SHA、坐标/列定义、统计和补充记录；[catalog](../../results/catalog/ldo_r4.json)是小索引。原始波形、deck、execution及冻结source在本机results，不随git迁移。

| 边界 | campaign尾名 | 发布数量 |
|---|---|---:|
| 校准 | `r4/20261110T111227.910607Z_2c6e23d2` | 1088 |
| 独立HV/host/温度/负载 | `r4/20261110T112415.433032Z_31c78a41` | DC1215/AC255 |
| 无源卡 | `r4_passive_card/20261110T111228.178530Z_7224790f` | 27 |
| 启动/静态旁路 | `r4_startup/20261110T113541.207446Z_8767c44a` | 18 |
| 独立DC噪声 | `r4_dc_noise/20261110T120141.651192Z_9a75685f` | 18 |
| 尾偏置100k/16p | `r4_bias_filter/20261110T112350.767887Z_4f102ee3` | 3 |
| 尾偏置1M/16p | `r4_bias_filter/20261110T113540.869125Z_59f58e7a` | 3 |
| 额外quiet电容 | `r4_cap_load/20261110T120319.075181Z_64e49ca1` | 16 |
| 额外100pF端点ll/tt/hh | `r4_cap_pvt/20261110T124405.408601Z_ad913485` | 255 |
| 额外100pF端点hl/lh | `r4_cap_pvt/20261110T125237.670359Z_af15b6b4` | 170 |
| 电阻热噪声卡 | `resistor_noise_check/20261110T111240.488278Z` | 4器件 |

读取完整清单并复核/重画：`uv run python verification/plotting/ldo_r4.py`。不启动ngspice，须有本机results与相同PDK；仅有git的环境可审查已发布摘要，不能称为raw复核。

端点补测另见[数据与命令输入](../data/ldo_r4_pin_cap.json)、[catalog](../../results/catalog/ldo_r4_pin_cap.json)，由`verification/plotting/ldo_r4_pin_cap.py --base ... --endpoint ... --crossed ...`读取三份明确summary重画，不混入原九项基线清单。

保留但排除：早期xhigh参考电阻活动`r4/20261110T110933.041892Z_f3aa54e9`已显式终止；startup末尾旧noise偏置不成立；DCnoise `20261110T114706.769581Z_464b47a0`也被pass电流检查器拒绝。有效噪声必须使用上表campaign与清单所列新分析，不将旧约6µV数值混入。

## 可外发的只读复核包

适合外部小模型完成，不占仿真名额。限定读取以上文件和本机引用结果，**不改DUT、不启动ngspice、不改共享状态、不提交**。

1. 用JSON坐标检查DC1215、AC255的唯一性/覆盖；确认每MOS/RC的电压码跨HV/host/T/load固定。TT±90mV是确定性压力，不是MC。
2. 选TT、最低电压、最低PSRR/PM、最大启动峰/最慢尾偏置、1nF电容点，核对deck/execution/输出SHA和实际负载/时间窗口；不能仅看exit_code。
3. 将静态外供strap、关断漏电、外接电容约束、独立tail路径和噪声口径逐项与文档核对。区分grid无瞬态OP回退、noise逐次pass电流一致以及全部慢节点认证三件事。
4. 在`docs/work_packages/deliveries/WP-LDO-002/`交付`summary.md`、`evidence.json`及正常`.py`采集脚本。无raw或PDK时交summary-only并列缺项。集成者独立复核后决定结论，不自动提升资格。

## 集成者下一步

先画出供电域连接表，审查VCO/首buffer/CP/LF/预充/码驱动/窗口门限的host与quiet归属。tail滤波仅移动gate侧，保留本地二极管和电流拷贝在原侧。原宿主VDD比例门限需要检查，不能在quiet恒1.8V时仍默认host=quiet。

提取真实负载和实际gate/分布电容，100pF理想端点PVT已补；继续真实quiet引脚模型和电容区间，再安排有价值的短启动/捕获/切码/负载阶跃联合验证。原r3动态测量不可直接标为r4已完成；已有PLL集成不需要从头再证明。

随后补电压码存储/工厂测量流程、quiet和bias-ready与失效复位边界；模型侧以r4实际传递重算两电源与尾偏置路径，明确共享BG相关噪声，再决定PLL噪声实验。HV/PNP局部随机模型有缺口，先做采样/几何审计，不能直接跑通用MC后宣称完整失配资格。

当前Codex无运行中仿真，保留两名额供后续约定使用。Claude的PSRR与bias_path_ac、供电容限模型仍是独立进行中工作，本次提交不代其合入；RX/TX/粗码等旧工作树改动保持原状。VCO降至1.5V留作未来迭代。
