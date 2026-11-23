# 共享激励

所有源均为理想、确定性输入，以传入 vss 为参考；默认数值只用于自检。

| 文件 | 用途 |
|---|---|
| clock_cmos.spice | 单端时钟 |
| cml_diff_clock.spice | 恒定共模的差分时钟，vdiff_pp 为差分峰峰值 |
| cml_diff_sine.spice | VCO 类差分正弦输入；每端振幅 vdiff_pp/4 |
| pfd_clock_pair.spice | 独立相位和频率的参考/反馈时钟 |
| cp_pulse_pair.spice | 独立 UP/DN 脉宽及相对位置 |
| vctrl_ramp.spice | 动态控制斜坡，静态调谐应逐点稳定测量 |

需要源阻抗时由夹具添加；理想差分源不模拟真实 CML 输出阻抗。
脉宽及周期应满足边沿时间约束。
专用 PWL 放在模块 tb/<case>/stimuli/，通用源放此处。
后续 PRBS、相位调制、供电干扰和随机抖动单独命名，注明归一化与噪声带宽。
