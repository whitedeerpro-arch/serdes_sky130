# RC退化CTLE初稿

权威实现为[rx_ctle_rc.spice](spice/rx_ctle_rc.spice)。端口顺序：inp、inn、outp、outn、eq0、eq1、vbias、vdd、vss；输出差分极性与输入相同。

eq0/eq1为1.8 V静态控制，eq0为低位。源极之间固定600 Ω，实际TG连接200/400 fF支路。00是最小峰化模式，保留放大器和共模转换路径；不是直接短接输入输出的物理旁路。电容/电阻仍为理想名义元件，开关和电流sink为SKY130 MOS。

外部50 µA参考通过W8/L0.5 LVT参考管，驱动两个W48/L0.5 LVT sink。参考电流本身仍理想，尚无片内基准或校准。测试输出负载20 fF/端是未来采样器预算，不是已接入采样器。

已做16组DC/AC及6 dB真实通道电压记录的4档CTLE独立回放。实际门输入加载已在真实驱动器/PCB/CTLE缩小模型中联合验证，见[加载联调](../../../docs/rx_loaded_link.md)。实际采样器、CDR、噪声/失调/PVT仍待验证，详见[设计与结果](../../../docs/rx_frontend_first_design.md)。
