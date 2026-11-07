# RX W40 冷角全链读出：缺口定位

固定 WP-003 十个来源中，FS 1.65 V −40 °C / R hh 有一次当前边界的正式尝试超时、一次 smoke 在初始工作点数值失败，均无完整波形；FF 1.95 V −40 °C / R hh 没有该边界的正式尝试。两处都不能判为电路功能失败，也不能由相邻边界通过推断当前全链通过。下一步应先拆分数值/启动与模块行为，依次观察采样、读出 ÷2、转换和 Johnson，再考虑全链回归；不要直接启动长 MC。

## 证据边界与实际尝试

[当前修订](../../../config/rx_working_revision.toml)为 `serdes_rx_readout_deser16`，读出分频 `divider_hold_width_um=40`；采样窗口的 45×tt/hh/ll 数据不包括读出及 deser16 负载，不能填补全链缺口。[WP-003 事实表](WP-003/evidence.json)列出固定源及文件哈希，[摘要](WP-003/summary.md)给出每个边界的完整性定义。

| 条件及尝试 | 身份 | 实际结果 |
|---|---|---|
| FS 冷 hh [正式 deck](../../../results/analog/rx/sampler/readout_deser/20261105T195801Z_ac_trim32_realbias_rhh/fs_v1650_t-40/tb.cir)、[日志](../../../results/analog/rx/sampler/readout_deser/20261105T195801Z_ac_trim32_realbias_rhh/fs_v1650_t-40/simulator.log)、[执行](../../../results/analog/rx/sampler/readout_deser/20261105T195801Z_ac_trim32_realbias_rhh/fs_v1650_t-40/execution.json) | `fs_hh`、PDK R 快照、真实 bias、W40，PI20、trim32、`rb=2k`；`14796a6-dirty` | 2,400.1 s 超时，exit null、无 raw；日志有 initial transient solution，但没有终点/最后 transient 时间，因此实际仿真进度未知。目标 44.75 ns，8 ns 后保存。未得到可评价的映射或功能结果。 |
| FS 冷 hh [后续 smoke deck](../../../results/analog/rx/sampler/readout_deser/20261105T213614Z_ac_trim32_realbias_rhh/fs_v1650_t-40.smoke/tb.cir)、[日志](../../../results/analog/rx/sampler/readout_deser/20261105T213614Z_ac_trim32_realbias_rhh/fs_v1650_t-40.smoke/simulator.log)、[执行](../../../results/analog/rx/sampler/readout_deser/20261105T213614Z_ac_trim32_realbias_rhh/fs_v1650_t-40.smoke/execution.json) | 同 `fs_hh`、W40、真实偏置快照；`14796a6-dirty`，加入 `gminsteps=100 srcsteps=100`；smoke 目标 9 ns、8 ns 后保存 | 日志记录 transient OP 未收敛、initial timepoint timestep too small，报 trouble `xbias_ref.xbg.xq1` PNP；随后无法写向量，无 raw。exit code 0 不代表成功。这是数值失败，不足以证明带隙或读出功能失效；没有正式运行。 |
| FS 冷旧 [首试](../../../results/analog/rx/sampler/readout_deser/20261103T124408Z_ac_trim32/fs_v1650_t-40/simulator.log) / [r2](../../../results/analog/rx/sampler/readout_deser/20261103T124408Z_ac_trim32/fs_v1650_t-40.r2/execution.json) | 理想参考电流、`fs`、非指定 hh；动态 include，无历史电路快照，W40 身份不能确定；`8e6d726-dirty` | 首试 23.184835 ns timestep too small，日志指 `bc3n#branch`，目标 44.75 ns；r2 以 `reltol=0.001` 到 44.75 ns，输出完整但边界不同。无法移交为当前 W40 / 真实偏置 / hh 的通过。 |
| FF 1.95 V 冷 hh | 固定证据内没有当前边界 attempt、deck 或 log | 属于缺运行，不能称仿真失败。旧 [FF 冷](../../../results/analog/rx/sampler/readout_deser/20261103T124408Z_ac_trim32/ff_v1950_t-40/tb.cir) 为理想参考、`ff`、W 不明；[FF 冷 ll](../../../results/analog/rx/sampler/readout_deser/20261105T211808Z_ac_trim32_realbias_rll/ff_v1950_t-40/tb.cir) 是 W40/真实偏置但 `ff_ll`，均不等价 `ff_hh`。 |

两次 FS hh 的 snapshot `rx_readout_demux2.spice` SHA-256 均为 `b17492cf98fb4f9976e8389a49cbe5be2cb1b29b52550ea22f2a34a050461e57`，`rx_readout_deser16.spice` 均为 `7414924fae588440d4996938738a6becfdcfe46aa364165f9593d995c6b08f81`，与本次检查时工作区对应文件相同；前者参数 `div_whold=40` 传给 `Xdiv`。这些哈希只确认所比文件，不证明所有依赖完全相同或两次 `dirty` 工作树相同。正式和 smoke 的 deck hash 分别是 `1d9abd7fce707f7eee7edc74e600421f3f57a8d790f005963e33918c9bc12b15` 和 `020aa90b6dcaabb9e0536a2211057a5ad59e1e6c0c1e0853f828818e0ddf9d7f`；后者改变了求解步进和结束时间，不能当作仅缩短的同一尝试。

## 激励、初值与解释

两份 FS hh deck 没有 `.ic`，有 `.nodeset`：`bias_vbg=1.23`、`xbias_ref.xbg.s=1.23`、`xbias_ref.vg=0.9`、`vgi_bias=0.9`、`xbias_ref.xbg.ta/tb=0.95 V`，用于 DC 求解辅助；不是上电轨迹或启动保证。VDD 和 Vref 为恒定 1.65 V，`trim=15` 真实偏置，EQ 两位均为 VDD；采样 trim 32，PI code 20。时钟是理想行为源 2 GHz，四对相位 0/45/90/135°，每支相对 `VDD−0.15 V` 加减 `0.1·tanh(sin(ωt+φ)/0.25)`，标称差分峰峰 400 mV。t=0 时 c0p/n 均 1.50 V；c1/c3 约 1.5993/1.4007 V，c2 约 1.59993/1.40007 V（分别 p/n），不是四相零差分 DC。

远端激励来自固定 `stimuli.inc` 的理想 PWL：t=0 `rxp=0.969440 V`、`rxn=1.130560 V`，保持到约 8.001235 ns，再回放 C2 数据；为波形回放而非原生链路动态源。FF 冷 hh 没有 deck，不能替其声称相同 t=0 条件。

## 最小分层 probe 建议（待主控分配仿真）

1. 每个冷角以短 OP/瞬态先隔离真实偏置与上游 CTLE/PI/采样，保留各自 PDK R hh、真实供电、相同初始激励和负载签名；记录 `bias_vbg/vgi_bias/vbias`、收敛日志、CTLE/PI 输出、四相采样及 `rkp/rkn` 的幅度、共模、边沿与时间范围。分别尝试可追溯的求解辅助，仅视为数值诊断，不当上电验证；同条件正常偏置独立建立后再接负载。
2. 将实际或明确登记的 `rkp/rkn` 边界接到 W40 读出 ÷2 和原负载；测 `dqp/dqn/dmp/dmn`、尾电流、共模、摆幅、过零和连续分频。与已有 90 点 RX 负载 ÷2 单元图按条件和负载身份比对；单元结果不能替代全链。
3. 逐层接 CML→CMOS 转换，再接 Johnson/字时钟，分别记录转换输入输出、门限越界/亚稳、时钟相位、状态序列和误跳；保留多周期历史及初始化依赖，区分波形截断、缺时钟、错误状态及真正功能错误。先短窗口冒烟，记录每阶段完整终点和数据可用性。
4. 局部边界与收敛确认后，再运行两角完整采样→读出链、检查位映射和时钟健康及实际规格。真实上电、原生 PLL 相位、失配和 MC 均仍待独立验证；求解器调整、初始辅助或边界替代必须与电路修改明确区分并记录。

## 固定十目录之外：FF 冷 hh 历史尝试

以下为另外直接抽看的历史固定目录，不改变 WP-003 的十目录审计。它们均是 `ff_hh`、PDK 电阻快照和真实偏置，deck 包含 `serdes_rx_half_rate_samples_ac_trim_rk`（`rb=2k`）及 `serdes_rx_readout_deser16`，PI20 / trim32；全部无 raw，不能产生完整功能判断。注意这里的 W80 指**读出 ÷2 的保持管**，不是 demux 数据 DFF 的独立 `dd_whold=40`。

| 固定目录及尝试 | 快照中实际 ÷2 | deck 设置、执行及日志 |
|---|---|---|
| [20261104T193407Z 正式](../../../results/analog/rx/sampler/readout_deser/20261104T193407Z_ac_trim32_realbias_rhh/ff_v1950_t-40/execution.json) / [deck](../../../results/analog/rx/sampler/readout_deser/20261104T193407Z_ac_trim32_realbias_rhh/ff_v1950_t-40/tb.cir) / [log](../../../results/analog/rx/sampler/readout_deser/20261104T193407Z_ac_trim32_realbias_rhh/ff_v1950_t-40/simulator.log) | W80，源跟随器时钟 | 默认 `reltol=1e-4`，7200.1 s 超时，exit null；日志无完成时间、无明确 transient OP 错误，实际推进时间未知。目标 44.75 ns。 |
| [20261105T032618Z 正式](../../../results/analog/rx/sampler/readout_deser/20261105T032618Z_ac_trim32_realbias_rhh/ff_v1950_t-40/execution.json) / [deck](../../../results/analog/rx/sampler/readout_deser/20261105T032618Z_ac_trim32_realbias_rhh/ff_v1950_t-40/tb.cir) / [log](../../../results/analog/rx/sampler/readout_deser/20261105T032618Z_ac_trim32_realbias_rhh/ff_v1950_t-40/simulator.log) | W80，源跟随器时钟 | `gminsteps=srcsteps=100`、`reltol=1e-4`，98.2 s，exit 0 但 transient OP 失败、0 数据行；initial timepoint timestep-too-small，节点 `xdut.vck`，无可写向量。目标 44.75 ns。 |
| [20261105T040645Z smoke](../../../results/analog/rx/sampler/readout_deser/20261105T040645Z_ac_trim32_realbias_rhh/ff_v1950_t-40.smoke/execution.json) / [deck](../../../results/analog/rx/sampler/readout_deser/20261105T040645Z_ac_trim32_realbias_rhh/ff_v1950_t-40.smoke/tb.cir) / [log](../../../results/analog/rx/sampler/readout_deser/20261105T040645Z_ac_trim32_realbias_rhh/ff_v1950_t-40.smoke/simulator.log) | W80，源跟随器时钟 | `gminsteps=srcsteps=20`、**deck 实为 `reltol=1e-4`**，3600.1 s 超时、exit null；无明确 OP 报错及已知推进时间。smoke 目标 9 ns，非正式结果。 |
| [20261105T050721Z smoke](../../../results/analog/rx/sampler/readout_deser/20261105T050721Z_ac_trim32_realbias_rhh/ff_v1950_t-40.smoke/execution.json) / [deck](../../../results/analog/rx/sampler/readout_deser/20261105T050721Z_ac_trim32_realbias_rhh/ff_v1950_t-40.smoke/tb.cir) / [log](../../../results/analog/rx/sampler/readout_deser/20261105T050721Z_ac_trim32_realbias_rhh/ff_v1950_t-40.smoke/simulator.log) | W80，源跟随器时钟 | `gminsteps=srcsteps=300`、`reltol=1e-4`，127.3 s，exit 0 但 transient OP 失败、0 数据行，initial timepoint `xdut.vck` timestep-too-small，无可写向量；目标 9 ns。 |
| [20261105T065521Z 正式](../../../results/analog/rx/sampler/readout_deser/20261105T065521Z_ac_trim32_realbias_rhh/ff_v1950_t-40/execution.json) / [deck](../../../results/analog/rx/sampler/readout_deser/20261105T065521Z_ac_trim32_realbias_rhh/ff_v1950_t-40/tb.cir) / [log](../../../results/analog/rx/sampler/readout_deser/20261105T065521Z_ac_trim32_realbias_rhh/ff_v1950_t-40/simulator.log) | W80，已改为 AC 耦合读出 ÷2 | 默认 `reltol=1e-4`，3600.1 s 超时、exit null；无明确 OP 报错及已知推进时间。目标 44.75 ns；`bcc4b32-dirty`，不能与前述源跟随器版本等同。 |

W80 判据来自各 campaign 的 `pdk_resistors/analog/rx/sampler/spice/rx_readout_demux2.spice` 和 `pdk_resistors/analog/pll/divider/spice/cml_div2.spice`：前三类调用 `pll_cml_div2` 未覆盖 `whold`，后者默认 80；065521 调 `pll_cml_div2_ac` 未覆盖 `whold`，其默认同为 80。[055022](../../../results/analog/rx/sampler/readout_deser/20261105T055022Z_ac_trim32_realbias_rhh/plan.json) 的 plan 只有 `ss_v1650_t85`，没有 FF 冷尝试，不能将其误记为 FF。先前 `7598a0f-dirty` 与后来的 `bcc4b32-dirty` 不是可复原的完整源码身份，应以每份快照和 deck 为准。

[设计记录](../../design/rx_pi_sampler.md)提到 `op-steps 20`、`reltol=1e-3` 的一小时尝试；上述 040645 的 deck 实际为 `1e-4`，065521 则没有 opsteps 且为 `1e-4`。本次枚举的 FF 冷 readout_deser deck 未定位到与该组合完全一致的一小时尝试，需另找具体运行身份；不能把这两个 deck 改述成该设置。当前 W40 的 FF hh 在 WP-003 固定十目录内没有正式尝试，以上查到的额外 FF hh 也都是 W80，不能用它们替代 W40 测试。

## 偏置 DC 参考与节点种子可用性

固定 [dist_pvt summary](../../../results/analog/common/bias/dist_pvt/20261103T212249Z/summary.json) 共 135 行；下列两个所需 TSV 均存在、各含一行有限结果，与 summary 一致，两个 deck 的 execution 均 exit 0、无登记 log failure。它们是 DC 工作点，不是 RX 启动或完整链收敛结果。

| MOS / 供电 / 温度 / R | vbg / V | vgi / V | v_cml / V | v_ctle / V | i_cml / µA | i_ctle / µA |
|---|---:|---:|---:|---:|---:|---:|
| FS / 1.65 V / −40 °C / hh | 1.226562 | 0.977051 | 1.051571 | 0.721796 | 192.549 | 45.716 |
| FF / 1.95 V / −40 °C / hh | 1.236737 | 1.236267 | 0.971272 | 0.660091 | 193.959 | 45.979 |

来源分别为 [FS deck](../../../results/analog/common/bias/dist_pvt/20261103T212249Z/fs_hh/tb.cir)、[FS TSV](../../../results/analog/common/bias/dist_pvt/20261103T212249Z/fs_hh/fs_hh_v1650_t-40.tsv)、[FS 执行](../../../results/analog/common/bias/dist_pvt/20261103T212249Z/fs_hh/execution.json) 和 [FF deck](../../../results/analog/common/bias/dist_pvt/20261103T212249Z/ff_hh/tb.cir)、[FF TSV](../../../results/analog/common/bias/dist_pvt/20261103T212249Z/ff_hh/ff_hh_v1950_t-40.tsv)、[FF 执行](../../../results/analog/common/bias/dist_pvt/20261103T212249Z/ff_hh/execution.json)。两 deck 通过 `option temp=-40` 与 `alter Vdd` 选择表中条件，库段分别是 `fs_hh` 和 `ff_hh`。两原始日志的部分其他 OP 步骤出现 dynamic gmin stepping warning；目标 TSV 的单行输出存在且执行整体结束，这些 warning 不等同于目标点失败，也不提供动态验证。

结构上，dist deck 的 `Xref ... serdes_bias_ref` 未显式指定 trim；目前读取的 `bias_dist.spice` 默认 trim=15，失败 RX deck 中的 `Xbias_ref ... serdes_bias_ref trim=15` 与之对应。dist 的 `Xccml ... serdes_bias_pcopy n=85` 和 `Xdcml ... serdes_bias_cml` 对应 RX 的 `XIref ... n=85` 与 `Xref ... serdes_bias_cml`；当前定义中 CML 二极管为 `nfet w=5 l=0.5`。dist 的 CTLE n=20 与 `serdes_bias_ctle` 的 LVT 二极管 `w=8 l=0.5 nf=4`，对应 RX `XIctle n=20` 和 `Xcbias` 的同尺寸二极管。RX 两个所查冷角供电和库段与各 DC 点相同；RX 四个 bias_i 节点与 dist 的 i0–i3 均接 0.7 V。

身份限制：dist 原 deck 直接 include 工作区路径，并未在该目录保存电路快照，`320d2f2-dirty` 不能唯一恢复当时的 cell 内容；上面的默认 trim、CML 尺寸和复制单元对应关系是**按当前源码及 RX 快照检查的结构对照**，不能证明 dist 运行时源码字节完全相同。当前 `bias_dist.spice` 和 FS/FF RX PDK 转换快照的 SHA-256 均为 `722d10730b79f848e77e1bb56ca7abb92428a62c3f9afa1feada364a93cdf012`；RX 的 bandgap 快照是 PDK 电阻转换后文本，不能直接与 dist 运行时未保存的动态 include 判为同字节。

负载也不同：dist 同时放 CTLE 和 CP 偏置支路，及 CML 二极管上额外 `w=20 l=0.5 nf=4` 尾管与 500 Ω PDK 电阻/1 V 代理，另有理想参考比较支路；完整 RX 的 `vbias` 驱动 PI、采样器及读出链，`vctle` 驱动真实 CTLE，时钟和数据电压源提供不同 DC 条件。额外栅电容、漏电、供电和内部节点会改变工作点及收敛路径。dist 的 `vbg/vgi/v_cml/v_ctle` 可分别映射为 RX 的 `bias_vbg/vgi_bias/vbias/vctle`，**仅适合作为 bias-only 对照和后续 `.nodeset` 候选**；先在同一 RX cell 快照、trim、供电/角及负载条件下校准偏置，并逐项记录初值及结果。不得直接视作当前 RX 可收敛或 warm-start 已验证；不采用 `.ic` / `uic`，也未注册跨 bench 边界或启动任何仿真。

来源 SHA-256：summary `1c8308b3ec62cb53660f7c79fe0cd85b3977bcd5c400030b11c582e61b2837a2`；FS deck `609397a45ae8479136f41dd2d4d041ea7a8730f7b738d6f196c6650b9f58e80a`、TSV `f142c70495cffdaf8f264892c3c24bb70d374dc6bd2bdea791d585ca0fc0084c`、execution `87556b7e788376b649118c7c1f62ef25eb48508bbcb933ce483b28037b886ca2`；FF deck `877e902987d22f8881d418653fac2827f795fdc12464d044834f582afc83c901`、TSV `606bf6852e1fc20953ff4a20f23c9d6a864319e2f9624e2a1010d9c51822b2be`、execution `080c7d2ae4a8b304dcaa79a7c1c18186dab3553607816678b3ca5d1b772a65c7`。
