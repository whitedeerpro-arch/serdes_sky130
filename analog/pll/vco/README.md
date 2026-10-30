# VCO 压控振荡器

四级差分 CML 环振原型，3 bit MIM 电容阵列粗调、SKY130 LVT 变容管细调。
最高配置目标为 2 GHz，差分峰峰值约 400 mV；输出留出八个相位抽头。

状态：晶体管级探索原型。已做部分 TT 确定性瞬态与变容管导纳分析；尚未完成完整 PVT、提取或相噪验证。
真实时钟接收器及可选 CML 缓冲现已做 TT 联调，见 [后续结果](../../../docs/cml_clock_receiver_results.md)；
本模块独立测试仍保留代理电容，供分离观察 VCO 本身。
首轮数据与波形见 [设计结果](../../../docs/vco_ring4_first_results.md)，输入目标见 [spec.toml](spec.toml)。
接口与时钟分配见 [串化时钟方案](../../../docs/serdes_clock_plan.md)。
公共差分单元在 common/cml_buffer/spice/cml_delay_resistive.spice。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [startup](tb/startup/case.toml) | block | startup_success, startup_time, frequency, differential_swing, power |
| [tuning](tb/tuning/case.toml) | block | frequency, kvco, differential_swing, output_common_mode, power |
| [sensitivity](tb/sensitivity/case.toml) | block | supply_pushing, load_pulling, frequency, swing, power |
| [phase_noise](tb/phase_noise/case.toml) | block | phase_noise_vs_offset, integrated_phase_noise, integrated_jitter |
| [varactor_cv](tb/varactor_cv/case.toml) | block | effective_capacitance, conductance, quality_factor |

结果：`results/analog/pll/vco/<case>/<run_id>/`。prototype 表示已有探索测试，不表示设计规格通过。

spice/vco_ring4.spice 的端口依次为四组 q0p/q0n 到 q3p/q3n、vctrl、b0/b1/b2、vbias、vdd/vss。
b0 为最低位，1 接 vdd 表示加入电容；所有级与两根输出使用相同代码。
偏置端由外部电流参考和二极管连接的镜像器件驱动；完整参考源尚未设计。
负载电阻暂为理想元件。已探索每端 5 fF 和 20 fF 代理负载；当前模板使用 20 fF，
仍不能替代真实电平转换器的输入阻抗与反向耦合。

测试台 .cir.in 需替换 MODEL_LIBRARY、CORNER、PROJECT_ROOT 标记，放入独立运行目录。
从该运行目录的 raw/ 启动，raw/.spiceinit 设 ngbehavior=hsa，使用 ngspice 47。
wrdata 在当前目录生成 waveforms.tsv；启动时采用一次有限扰动，21 ps 后撤除。
无噪声的完全对称初值不能作为自发起振保证，供电爬升和失配启动仍待验证。
