# 运行结果与归档入口

`results/` 保存本地仿真、版图装配与签核产物（由 `.gitignore` 排除，本说明与 `results/catalog/` 索引入库）。现行采用状态与验证边界统一见[当前状态](../docs/status/current.md)，完整证据与退役清单见[结果索引](catalog/README.md)。

## 关键签核与证据索引

- [5G 双速签核台账（2026-11-26）](catalog/serdes_5g_signoff_20261126.json) — 8/8 模拟宏 CPEX/RCX、32-bit 数字宏 `v4p1`、紧缩混合去耦瓦片与 Plan-C 全片物理签核
- [4G / 5G 片级物理审计（2026-11-26）](catalog/chip_physical_audit_20261126.json) — `full_v8`（4G）与 Plan-C `v4p1`（5G）只读连通性、金属 stub 与密度审计
- [v1.0 4G 子系统证据索引](catalog/v1_0_subsystem_evidence.json) 与 [4G 片级集成证据](catalog/chip_integration_20261124.json)

## 本机波形软链接

当 `/home` 余量紧张时，大波形可用 [waveform_archive.py](../verification/maintenance/waveform_archive.py) 转存至 `/opt/serdes_archive`，原路径保留文件软链接，读取与断点续跑沿用原路径（2026-11-26 整理已清理历史原始波形以释放磁盘空间）。

```bash
uv run python verification/maintenance/waveform_archive.py verify
uv run python verification/maintenance/waveform_archive.py restore results/某个运行目录
```

所有退役清单（`catalog/retired_*.json`）可用[维护与校验工具](../verification/maintenance/README.md)核对归档文件完整性与哈希。

## 目录结构与路径说明

```text
results/
  catalog/                           入库证据台账、物理审计、波形归档与退役清单
  analog/<模块>/<实验>/<run>/         SPICE 输入快照、日志、指标 JSON 与波形（含软链接）
  digital/                           RTL / VCS SDF GLS 与 P&R 独立验证产物
  layout/                            宏级与片级（4G full_v8 / 5G Plan-C）装配、DRC/LVS 与审计产物
  layout_review/                     阶段版图独立提取与寄生复核产物
  verification/                      顶层联调、项目复核固定副本与信道分析产物
  maintenance/                       波形归档逐文件清单与磁盘巡检记录
  archives/                          历史只读 tar.xz 打包归档（不再新增）
```

Bias 与 LDO 源码升到 `analog/bias/` 和 `analog/ldo/` 后，历史运行仍保留在 `results/analog/common/{bias,ldo}/`。如本地需要旧台读取同路径历史数据，可按[v1.0 证据索引](catalog/v1_0_subsystem_evidence.json)核对运行身份后按需建立软链接：

```bash
ln -sT common/bias results/analog/bias
ln -sT common/ldo results/analog/ldo
```

详见[测试与结果约定](../docs/verification/methods.md)。
