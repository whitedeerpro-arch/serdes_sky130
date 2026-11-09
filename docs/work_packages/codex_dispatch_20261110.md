（Claude 协作消息。所有者 11-09 22:38 让 Claude 回来继续工作，并让两边协同、把 Codex 恢复后的额度用足。）

请先读 docs/work_packages/collaboration.md（Claude 已提交 84ea245），它是这一轮的分工、仿真名额和提交规矩。要点：

1. 仿真名额：全机 ngspice ≤ 4，Codex 2 个、Claude 2 个；开跑前 `pgrep -x ngspice | wc -l`。
2. 范围：Codex 继续自己的线——PLL 粗码窗口/上门限/上电停止门限/切码动态预算、RX 冷角读出复核、WP-007 ISF pilot。Claude 负责监测工具包（analog/common/monitor、digital/common）、PLL 第 7 步电源抑制与噪声、PFD/反馈接收器 MC、启动链顶层 RTL；这些不要改。
3. 提交：只 `git add` 自己的路径；不 reset/stash/checkout 对方文件。工作区里 Codex 上次额度用尽时留下的未提交改动（清单在 collaboration.md）由 Codex 复核后提交。Claude 在 Codex 离开期间的提交：803ef53（窗口门限失配 σ 及对粗码的影响）、84ea245（协作约定）。
4. 任务队列按 collaboration.md「Codex 的任务队列」顺序做：收尾提交 → 上电停止门限在实测曲线上复算（带每芯片随机门限误差）→ 粗码动态预算 → WP-007 → 其余不重叠的闭合项。
5. 每完成一项，在 collaboration.md 末尾状态区追加一行（本地时间、提交号、一句结论）。全部完成时在最后一条消息末尾写 QUEUE_DONE；额度将尽时留下可续状态并写 QUOTA_LOW。

所有者偏好不变：中文、结论先行、模型先行、results 只追加、全部 45 个 PVT 条件满足规格。

---

续派文本（Codex 一轮结束、额度还在时）：

继续 docs/work_packages/collaboration.md 中你的任务队列：若上一项结果还没追加到状态区先追加，再做下一项。仿真名额仍是 2 个。全部完成时在最后一条消息末尾写 QUEUE_DONE；额度将尽时留下可续状态并写 QUOTA_LOW。
