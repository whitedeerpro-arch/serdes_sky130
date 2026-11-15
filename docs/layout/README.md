# 版图文档入口

[2026-11-15 PLL 独立审阅](pll_review_20261115.md)连接各模块的布局判断、提取与局部电气结果。项目级采用状态仍只查 [current.md](../status/current.md)，执行顺序查 [计划](../status/prelayout_plan.md)。

模块的 `analog/.../layout/README.md` 是稳定入口；`review.md` 写人工结论与边界；`plan/` 放规划；`variants/<身份>/` 放几何、独立参考和必要预览/小摘要。运行日志、EXT、临时脚本及波形留在追加式 `results/`，通过 `results/catalog/` 的固定路径和哈希引用。历史生成快照不反向改写。

路径维护采用普通工程约定：代码从 `project.ROOT` 或 `__file__` 定位；文档使用相对链接；迁移使用 `git mv` 并同时更新直接引用，提交前运行已有的 `uv run pytest -q tests/test_doc_links.py`。对外使用过的旧文档入口必要时保留短跳转页。不要全仓库重写历史 deck 的绝对路径；新运行递归复制项目 include 为快照，已生成 deck 继续引用其副本。重建 deck 时若源码迁移导致输入身份变化，续跑会拒绝，使用新的 campaign，不静默复用旧结果。

本次把 VCO 的实际几何截图从 `plan/` 移到 `variants/sym9_pdk/views/`，直接引用统一迁移并检查。无需引入复杂路径注册系统，也不靠人工逐次发现断链。

PFD、接收器、÷8 和 LF 的源码候选目录中原有的原始 EXT/日志已移入结果归档，逐文件哈希与旧/新位置见 [迁移清单](../../results/catalog/pll_layout_source_exports_20261115.json)。生成器安装步骤同步停止复制原始日志；几何和电气快照的身份不变。
