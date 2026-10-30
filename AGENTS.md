# 接手约定

这份文件写给接手本项目的 agent（以及项目所有者自己）。项目会在不同 agent 之间迁移，先读这里，再读 [README](README.md)。

## 项目与规格

SKY130、1.8 V、4 Gb/s SerDes：250 MHz 参考 → 2 GHz 四级 CML 环振 PLL → 16:1 CML 电流舵串化 → 100 Ω 线驱动；RX 为端接/CTLE → PI → 四相半速 CML 采样 → 数字 CDR → 16 位解串。

规格政策（2026-10-30 与所有者确认）：

- 45 个 PVT 条件（TT/SS/FF/SF/FS × 1.65/1.8/1.95 V × −40/27/85 °C）都必须满足功能和规格门槛：边沿散布 ≤ 0.15 UI、位中心有符号裕量 ≥ 75 mV、CML 摆幅目标 400 mVpp。
- **唯一允许缩水的是高低温下 4 Gb/s 的 BER。** 功能失败不能降格成"低质量通过"。
- 相位噪声/抖动必须做；抖动预算由设计推导，见规格文档。
- PPA 追求最优，但排在功能、PVT、噪声之后。
- 现有拓扑修补难度达到中等时，同时探索替代结构。

## 仓库与版本

- git 管理源码、文档、配置和小数据；`results/` 只保留在磁盘（索引 `results/catalog/` 入库）。基线用 git 标签标记，不再做"冻结"。
- 每个模块的当前修订记录在 `config/*_working_revision.toml`。`releases/v0.1-design-freeze-20261028/` 是历史基线，保持原样。
- 提交信息说明改了什么电路、跑了什么验证、结论是什么。

## 环境

| 项目 | 位置 |
|---|---|
| Python | `uv sync` 后 `uv run python …`（3.12，numpy/scipy/matplotlib） |
| ngspice | `/opt/ngspice47/bin/ngspice`（系统默认 ngspice 是旧版，不要用） |
| ngspice 共享库 | `~/.local/opt/ngspice47-shared`（混合仿真用） |
| Xyce | `~/.local/eda/bin/Xyce` 7.10，SKY130 兼容性未验证 |
| PDK | `config/pdk.toml`，sky130A，模型 `libs.tech/ngspice/sky130.lib.spice` |
| 数字 | Verilator 4.028、iverilog、yosys 0.9（旧），无 OpenSTA |

本机 8 核 / 7 GB 内存：并发 ngspice 不超过 4 个。TX 整链单点约 2 分钟，45 点约 1.7 CPU 小时。

## 仿真与结果

- DUT 只放电路；电源、激励、负载、测量放测试台。测试台模板在 `analog/**/tb/<case>/`，`@KEY@` 占位符由脚本替换。
- 每次运行写入 `results/<模块>/<测试>/<run_id>/`，只追加不覆盖；保留 `tb.cir`、日志、指标 JSON。大波形用无损 gzip。
- 执行成功不等于设计通过；没有规格的量记为 ungraded。
- 新代码写成正常的 `.py`。公共测量函数（边沿、眼图裕量、频率/相位、PVT 网格）收进共享库，不在每个 campaign 里重写。
- 新 bench 用 `spice.binary_output` 输出二进制 raw，并用 `spice.skip_output_before` 不保存分析窗口之前的启动段；`spice.Waves` 两种格式都能读。瓶颈在求解器，不在波形量（TX bench 文件小 58%，仿真时间不变）。
- 并发 ngspice 不超过 4 个：并发时单个仿真会慢约 25%，但总吞吐仍是串行的约 2.6–3 倍。
- 涉及时钟相对关系的实验，同时看"眼图健康"和"位映射"（`serial.bit_mapping`），不要只用固定位序的合同检查。

**历史脚本隐患：** 旧 campaign 的 `execution/*.txt` 从 `/tmp/serdes_*_campaign` 读路径，而这些文件指向原项目 `../simple_serdes`；旧 `tb.cir` 里也是原项目的绝对路径。不要直接运行它们，参照 `results/analog/tx/optimization/20261030T100258Z/execution/fork1_finalize.py` 的方式在内存里重定向，并且不要改写共享的 `/tmp` 文件。

## 文档

- 读者是所有者和接手 agent，不面向评审。
- 当前状态写在各模块设计文档里；按时间记录的实验笔记归入 `docs/history/`。
- 结论先行；适用范围和假设集中写在一节，不在每段重复免责声明；不写对话过程（"按用户指令"之类）。
- 正文手写维护，脚本只生成数据和图。
