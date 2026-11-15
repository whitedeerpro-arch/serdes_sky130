# PFD 版图入口

当前对象是 [标准单元 PFD](variants/pdk/README.md)，布局与寄生后结论见 [审阅报告](review.md)。根目录旧 `pll_pfd.mag` 是导入草案，不是当前验收对象。

| 位置 | 职责 |
|---|---|
| [build_pfd_sc_pdk.py](build_pfd_sc_pdk.py) | 从 PDK 标准单元生成几何与独立 LVS 参考 |
| [variants/pdk/](variants/pdk/) | 候选的 Magic、参考、提取网表与预览；同名文件不跨版本混用 |
| [寄生后测试台](../tb/layout_pex/run.py) | 对同一参考、CPEX 与原生 RC 做局部压力点比较 |
| [review.md](review.md) | 人工布局判断、通过范围和剩余风险 |

重新生成必须使用新的结果目录；检查日志、EXT、临时 Tcl 和波形留在 `results/`。本轮独立提取与运行身份由 [固定证据](../../../../results/catalog/pll_layout_review_pfd_20261115.json)绑定。

```bash
uv run python verification/layout/review_cell.py \
  analog/pll/pfd/layout/variants/pdk/pll_pfd_sc_dly_pdk.mag \
  analog/pll/pfd/layout/variants/pdk/pll_pfd_sc_dly_pdk_ref.spice \
  --output-dir results/layout_review/pfd_new --rc
uv run python analog/pll/pfd/tb/layout_pex/run.py \
  --physical-dir results/layout_review/pfd_new \
  --output-dir results/layout_review/pfd_performance_new
```
