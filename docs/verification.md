# 分层测试与结果收集

## 测试组织

| 层次 | 位置 | 关注点 |
|---|---|---|
| infrastructure | verification/smoke/ | 工具、激励和模型入口 |
| block | 各模块 tb/ | 独立功能、电气范围、噪声和失配 |
| integration | pll/top/tb/pfd_cp/、vco_divider/ | 相邻模块的电平、极性、脉宽和负载 |
| system | pll/top/tb/acquisition/ 等 | 闭环锁定、跟踪、抖动、杂散 |

实现视图 `behavioral / schematic / extracted` 是另一维度，不能与测试层次混淆。
行为级的锁定验证不能替代晶体管级起振或噪声验证。

`case.toml` 是测试定义文档，目前没有执行器。planned 表示尚未实现；prototype 表示已有探索测试，
仍有条件/视图待覆盖，不能解释为设计规格通过。
具体测试台命名为 `tb_<case>_ngspice.cir` 或 `tb_<case>_xyce.cir`。
共享激励在 `verification/stimuli/spice/`，专用 PWL 等放在 `tb/<case>/stimuli/`。

## VCO 与 PLL 分开测试

| DUT/测试 | 方法 | 收集项 |
|---|---|---|
| VCO 起振 | 固定 Vctrl，多个初值/上电过程 | 成败、起振时间、稳定窗口、频率、摆幅、功耗 |
| VCO 调谐 | 每个 Vctrl 单独起振、稳定、测频 | f(Vctrl)、局部 Kvco、幅度、共模、功耗 |
| VCO 敏感度 | 独立扫描电源和负载 | pushing、pulling、频率、摆幅 |
| VCO 相噪 | 按引擎验证振荡器噪声方法 | L(offset)、积分频段、相位噪声/抖动 |
| PFD | 独立正负相差/频差、异步复位、窄脉冲及步长复测 | UP/DN 脉宽、复位延迟、逐周期电压时间积分；不等于 CP 电荷死区 |
| 分频器/转换器/PFD | 真实电路耦合、对齐输入输出边沿 | 脉宽、边沿完整性、转换延迟、负载和分项功耗 |
| PLL 捕获 | 指定初始频差、相差、Vctrl | 频差、相差、周期滑移、锁定时间 |
| PLL 跟踪 | 锁定后注入相位/频率扰动 | 增益、带宽、峰化、恢复；区分行为模型和电路实测 |
| PLL 抖动 | 锁定后采边沿或适用的噪声分析 | TIE、周期/周期间抖动、PSD |
| PLL 杂散 | 锁定稳态频谱 | 参考杂散、谐波、RBW、窗函数、记录长度 |

### 有效性约定

- 未起振或没有足够稳态周期时，频率不可用，不能记为 0。
- 调谐曲线逐点稳定测量；快速控制斜坡只用于动态响应。
- Kvco 标明 Hz/V 或 rad/s/V、计算点及拟合区间。
- 每次记录稳定等待时间、测量窗口、求解最大步长、输出采样间隔、边沿阈值。
- PLL 锁定同时约束频差和有界相差，并持续指定时间。分频关系、相位展开/周期滑移的处理一并记录。
  判据尚待规格确定；不能只用 Vctrl 变平作为锁定证据。
- TIE 说明参考是理想时钟、输入参考还是拟合时钟，以及是否去除线性趋势。
- 无噪声瞬态的边沿变化不能直接归因于器件随机噪声。
- Xyce/ngspice 的模型兼容性和噪声方法分别验证。相噪测试尚未指定引擎；
  HB、普通小信号噪声或原始 FFT 不自动等于已验证的振荡器相噪流程。
- 执行成功与设计通过分开。未设置规格的测量为 ungraded。

## PVT 与统计

PVT 计划见 `verification/corners/pvt_plan.toml`。
单次运行固定工艺角、电源、温度、负载和实现视图。
统计运行另外记录随机种子、过程变化/局部失配开关及模型入口。
先确认统计参数确实改变实例参数，再开展 Monte Carlo；PVT 不代替失配分析。

## 结果路径

```text
results/
  analog/
    common/cml_to_cmos/<case>/<run_id>/
    pll/
      vco/tuning/<run_id>/
      vco/phase_noise/<run_id>/
      top/acquisition/<run_id>/
      top/jitter/<run_id>/
  infrastructure/stimuli/<run_id>/
```

run_id 使用 UTC 时间加引擎/角标识，例如 `20261027T120000Z_ngspice_tt_001`。
运行目录只追加，不覆盖。

| 产物 | 内容 |
|---|---|
| run.json | 测试、命令、版本、环境、参数、状态、来源 |
| metrics.json | 数值、单位、窗口、方法、规格和判定 |
| netlist/ | 顶层网表及输入快照/可追溯清单、初始化配置 |
| logs/ | 完整仿真输出和诊断 |
| raw/ | 波形、边沿、扫参表、频偏表等 |
| plots/ | 检查图；不能作为唯一数据 |

记录模板见 `verification/contracts/`。未知数值用 JSON null，禁止 NaN/Infinity。
execution_status 与 verdict 分开：仿真失败不能忽略，没规格不能判通过。
运行产物不提交版本库；需长期审阅的结论写入设计说明并引用 run_id。

VCO 调谐汇总按 Vctrl/PVT 对齐；PLL 锁定汇总按初始条件/PVT 对齐。
保留单次输入、原始数据和指标后，再生成各自的汇总，避免只剩一个全局 CSV。

### 阶段归档

用户授权在阶段收口时整理运行产物。2026-10-29起，≥1MiB的大波形/重复图可按原模块、实验和run_id无损归档；完整读回核对每个成员SHA256后才移走原文件。输入快照、日志、指标和当前验收窗口保留；历史指标、原始内容哈希及冻结版本不改写。具体规则见[保留策略](../verification/results/retention.toml)。

旧运行路径缺少大文件时，查询[归档索引](../results/catalog/artifacts.tsv)，用 `verification/results/artifact.sh restore 原路径` 恢复后再运行旧分析。哈希验证可使用归档账本中的原始字节哈希，归档文件另有独立哈希；不能把已归档误判为证据丢失。实验清单将执行状态、引用状态与设计判定分开，入口见[结果说明](../results/README.md)。

## 手工检查共享激励

从项目根目录运行，不加载 PDK，也不测试实际 DUT：

```bash
run_id=$(date -u +%Y%m%dT%H%M%SZ)_ngspice
run_dir="results/infrastructure/stimuli/$run_id"
mkdir -p "$run_dir/logs"
/opt/ngspice47/bin/ngspice -b \
  -o "$run_dir/logs/simulator.log" \
  verification/smoke/tb_stimuli_ngspice.cir
```

```bash
run_id=$(date -u +%Y%m%dT%H%M%SZ)_xyce
run_dir="results/infrastructure/stimuli/$run_id"
mkdir -p "$run_dir/logs" "$run_dir/raw"
/home/host/.local/eda/bin/Xyce \
  -l "$run_dir/logs/simulator.log" \
  -o "$run_dir/raw/stimuli" \
  verification/smoke/tb_stimuli_xyce.cir
```

十项检查值：CMOS 高电平 1.8 V、差分极值 ±0.4 V、共模 1.2 V、周期 10 ns、
控制斜坡终值 1.0 V、参考到反馈延迟 1 ns、UP/DN 的 50% 脉宽各 550 ps、
UP 到 DN 延迟 5 ns。ngspice 日志包含输出采样表；Xyce 另生成 .prn 文本波形表及 .mt0 测量文件。
测试夹具的 1 GΩ 电阻只为源自检提供连接，不代表实际 DUT 端接。
Xyce 输出语法参考 [官方用户指南](https://www.sandia.gov/app/uploads/sites/155/2022/02/Users_Guide.pdf)。

## SKY130 测试台

将 `config/ngspice/spiceinit` 复制到仿真工作目录为 `.spiceinit`。
确认启动日志显示 hs a 模式。模型入口使用 config/pdk.toml 的解析路径，记录实际版本与角。
`verification/templates/*.cir.in` 中的 @...@ 标记必须先替换，不能直接执行。
