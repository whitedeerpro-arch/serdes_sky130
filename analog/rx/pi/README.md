# RX相位插值器

共享2 GHz多相PLL、每RX独立PI-CDR的模拟时钟原型。本目录记录PI独立外部控制测试；后续已新增[真实采样器与交接RTL](../../../docs/rx_sampler_control.md)，物理重定时和数字CDR闭环仍未实现。

- `spice/pi_current_unit.spice`：A/B两对LVT输入管，一个真实NMOS尾电流，MOS开关选择该单位电流的输入相位。
- `spice/pi_sector.spice`：8个等权电流单元、600 Ω负载、每腿200 fF混合电容及CML恢复buffer；权重0..8。
- `spice/pi_clock_mux8.spice`：差分8选1传输门，外部onehot控制。
- `spice/pi_rotator.spice`：4个差分输入buffer、4个相位选择器及2个插值器，输出两对差分时钟，互补极性提供4个逻辑相位。整圈版本覆盖输出恢复级参数为W输入48 µm、W尾12 µm、600 Ω。
- `tb/sector/`：邻接45°锚点、9权重状态的静态模板。
- `tb/rotation/`：整圈64码静态模板、跨圈测试协议。
- `behavioral/`、`schematic/`、`layout/`：预留，尚无实现。

输入必须按相位**超前**0/45/90/135°排序。互补极性提供另4个锚点。不能照ring物理级号直接连接；需量测实际相位次序。输出dp/dn为数据0/180°，ep/en为边沿90/270°。

逻辑码c=8q+f，q=0..7，f=0..7。偶数扇区A=q、B=(q+1)%8、nB=f；奇数扇区A=(q+1)%8、B=q、nB=8-f。f0..f7为温度计码，前nB个置1。这样跨扇区可保持当前承载电流的输入不动，改变空闲输入。

静态模板中的@A0_V@..@B7_V@为onehot的0/1.8 V，@F0_V@..@F7_V@为温度计码。模板需替换PDK、工程路径和corner后运行；没有新增Python执行脚本。实际结果目录保存展开网表、命令、参数、PDK引用与输入SHA256。

晶体管DUT没有理想相位旋转器或理想输出增益。测试输入为理想相关2 GHz时钟，参考偏置使用外部理想850 µA电流及真实二极管连接MOS；R/C为名义理想元件。PLL加载、实际相位误差、采样器负载及kickback、失配/PVT/噪声不在当前结果内。每输出腿20 fF只是负载代理。

结果见[PI首版](../../../docs/rx_pi_first_design.md)，系统架构见[CDR方案](../../../docs/rx_cdr_architecture.md)。
