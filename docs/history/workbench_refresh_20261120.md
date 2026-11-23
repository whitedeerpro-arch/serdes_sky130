# 文档、工作台与波形整理（2026-11-20）

当前入口已对齐 r6q PLL、v3 TX 和 W40 RX 字路径。状态页记录采用组合和新版局部候选的证据边界，工作台的模块证据显示原图及其报告。系统框图的前一版可从本轮基点 `fae7eb5` 查询。[当前状态](../status/current.md)、[系统图](../figures/system/README.md)、[工作台](../../web/design/README.md)

- 根目录 `plot.pdf` 是旧版理想无源 LF 的单页 Xschem 导出，已退出源码根目录。原件可用 `git show d6bad1b:plot.pdf` 取回，SHA-256 为 `cf7838106b1d96277211d112aebf304aee82323badbfb9bbf5502ac94446f97f`。旧原理图入口仍可追溯，现行 LF 与紧凑候选按各自版图资料查看。[历史原理图](schematics.md)、[LF 版图](../../analog/pll/loop_filter/layout/README.md)
- 归档 352 个波形或历史打包文件，共 775,310,390 字节。首批按 72 小时和 1 MB 筛选，再归档已被 v7 取代的 SAFF v3/v5/v6 工况波形。原路径为直接可读的软链接，每份新入档文件按原路径重读并核对 SHA-256 与字节数。deck、日志、指标与固定引用继续可用。[批次清单](../../results/catalog/waveform_archive_20261120.json)、[恢复说明](../../results/README.md)

本轮只核对已有仿真与版图记录。SAFF-TSPC 的 FF 热角 0.10 GHz 理想时钟记录计数无错，已修正分频报告开头的错误表述。[分频报告](../design/pll_tspc_reclock_divider.md)
