# 工艺器件适配

spice/sky130_primitives.spice 对 SKY130 NMOS、LVT NMOS 和 PMOS 做薄封装，
统一总宽、指数量、共享扩散面积和周长的估算。调用前加载 SKY130 模型库。
不改变工艺模型；尺寸单位为 µm，依赖模型库的 1e-6 scale。
扩散几何仅供原理图探索，布局后以提取结果替代。
