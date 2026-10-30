# PLL与电流舵串化器设计定稿 v0.1

已按用户指令冻结，作为后续输出驱动/RX和独立测试的基线。冻结属于设计版本确定，不替代PVT、相噪或版图签核。

- [源码与参数快照](../releases/v0.1-design-freeze-20261028/README.md)、[逐文件哈希](../releases/v0.1-design-freeze-20261028/MANIFEST.json)、[打包文件](../releases/v0.1-design-freeze-20261028.tar.gz)。
- 末级A/B锁存器采用尾管24µm、每端200Ω，最终输出MUX仍为12µm/400Ω；新默认参数只改变两只锁存器。
- 新版已有256bit零错误/零额外漏跳变、0.04192UI散布、141.38mV最小位中心裕量。此前1024bit结果属于旧锁存器设置，不充作新版验证。
- PLL保留250MHz参考、÷8反馈、2GHz局部点及50µA/6.5kΩ/40pF/2pF。双节点预充和RTL监督器作为扩展一同冻结；片内预充参考/缓冲、细相位测量前端、看门狗和自动粗搜接口仍待实现。
- 原生冷启动扩展、PVT/噪声/失配/寄生和真实PLL源阻抗至串化器的联合资格验证由后续测试负责。所有理想源、无源器件和负载边界保留在证据中。

权威源为SPICE/RTL，既有原理图导出不作为本版依据。后续线驱动器与通道不在冻结范围；新增负载必须重新验证接口。

详细结果：[串化溯源](serializer_timing_root_cause.md)、[PLL启动](pll_startup_optimization.md)、[原生时钟及实际分发](physical_clock_distribution_results.md)。
