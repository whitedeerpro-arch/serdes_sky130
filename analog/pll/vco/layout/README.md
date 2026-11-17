# VCO 版图入口

**当前审阅对象是四级环＋四缓冲的 `sym9_s32p5` 候选，详细结论见 [review.md](review.md)。** 电路采用状态仍由 [项目当前状态](../../../../docs/status/current.md)决定，版图候选不自动替换原 r6。

| 位置 | 职责 |
|---|---|
| [plan/](plan/) | 参数化摆位、尺寸和走线通道规划，不存放实际版图截图 |
| [variants/sym9_pdk/](variants/sym9_pdk/) | 本次审阅的原几何、独立参考和视图 |
| [variants/sym9_clean/](variants/sym9_clean/) | 撤除浮空 field-poly 的独立候选及清理清单 |
| [variants/r6_pdk/](variants/r6_pdk/README.md) | 独立 bank、变容器及 CML 叶单元；错误的大环组装已撤销 |
| `build_*_sym9_pdk.py` | 分层生成 bank → half-tank → delay/buffer → ring/core |
| [清理工具](../../../../verification/layout/clean_field_poly.py) | 由 EXT 确认非器件、无接触孔的 field-poly 岛后，另建候选并重跑 DRC/LVS |
| [layout_pex/run.py](../tb/layout_pex/run.py) | 完整物理核的器件几何／CPEX／原生 RC 比较，固定偏置校准来源 |

运行中间文件、EXT、检查日志、波形和失败尝试统一留在 `results/` 的新目录。实际几何预览已从 `plan/` 移到 `variants/sym9_clean/views/`，所有文档引用同步检查；源码依赖通过 `project.ROOT` 或 `__file__` 解析，不依赖工作目录和原项目绝对路径。

```bash
uv run python verification/layout/review_cell.py \
  analog/pll/vco/layout/variants/sym9_pdk/pll_vco_core_sym9_s32p5.mag \
  analog/pll/vco/layout/variants/sym9_pdk/pll_vco_core_sym9_s32p5_ref.spice \
  --output-dir results/layout_review/vco_source_new
uv run python verification/layout/clean_field_poly.py \
  --source-dir results/layout_review/vco_source_new \
  --output-dir results/layout_review/vco_clean_new
```

这条清理链使原生成器与原几何可追溯，不在生成后手工改网表凑 LVS。后续重新规划接地 dummy 时须重新生成独立几何；不能恢复原浮空条并继承清理候选的性能数字。

寄生端点台的新钳位运行使用 `--bias-id pll_sym9_dc_bias@layout_review_20261115 --ramp`，从边界注册表解析固定来源并检查 DC 栅负载签名/波形哈希。`--bias-reference` 仅保留历史参数名，单独给一个来源路径不再接受为新运行的边界身份。

```bash
uv run python analog/pll/vco/tb/layout_pex/run.py \
  --physical-dir results/layout_review/vco_clean_new/physical \
  --top pll_vco_core_sym9_s32p5_clean \
  --output-dir results/layout_review/vco_ends_new \
  --points fs_v1650_t85:hh:0:1.21 sf_v1650_t-40:ll:31:0.90 \
  --variants cpex --bias-id pll_sym9_dc_bias@layout_review_20261115 --ramp
```
