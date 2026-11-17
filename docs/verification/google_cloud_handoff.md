# GitHub 与 Google Ultra 试跑

源码仓库：[whitedeerpro-arch/serdes_sky130](https://github.com/whitedeerpro-arch/serdes_sky130)。Git 保存已提交源码、文档、配置、小数据和结果索引；`results/` 的大波形、仿真日志/中间产物、`.venv` 与外部 PDK 不随推送上传。本地尚未提交的候选也不会因推送而变成采用实现。

## 存储与运行分开

| 位置 | 用途 |
|---|---|
| GitHub | 版本、源码、依赖锁定、文档与固定结果索引 |
| Google Drive | 按 campaign/工况保存波形归档、日志/指标与哈希清单；保存经过核对的工具/PDK 安装包 |
| Colab 运行时本地磁盘 | 解包源码、工具/PDK、输入后求解；完成一个工况就备份该工况 |

不要直接在挂载 Drive 的目录中运行大量提取/瞬态小文件 I/O。Google 官方建议把归档复制到运行时本地再解包；Drive 容量也不等于 Colab 虚拟机本地磁盘容量。[Colab FAQ](https://research.google.com/colaboratory/faq.html?hl=en)

## Ultra 资格

截至 2026-11-17，Google 官方列出的 Ultra 档位包含 20/30 TB 存储、1,000/2,000 Colab CCU 和较长后台执行，具体取决于订阅档位。Colab 权益还受地区、套餐管理者身份、正式付费而非试用等条件限制；实际以该 Google 账号的 Colab 订阅与余额页面为准。CCU、生成式 AI credits 和 Google Cloud credits 是不同权益，不能相互当作无限虚拟机预算。[Ultra 官方权益](https://support.google.com/googleone/answer/16286513?hl=en)

Ultra 仍不能视为永久运行、固定 CPU/内存或无限会话。当前 ngspice 47/KLU 流程没有接入 GPU/TPU 求解；本项目试跑先核实 CPU、内存和每工况成本，不因获得高端 GPU 就扩大并发。

## 第一轮试跑

1. 在 Colab 本地工作盘 clone 仓库，记录明确 commit；执行 `uv sync` 获取项目指定的 Python 3.12 环境。
2. 安装 ngspice 47，按 `config/pdk.toml` 的 installation id 准备同版 SKY130。先用实际工具版本和一个工作点/短瞬态核对，不能采用系统旧 ngspice 冒充。
3. 在云端工作副本中把 `config/tools.toml` 的 ngspice 路径和 `config/pdk.toml` 的 PDK 路径改为实际安装位置，保留工作差异并在新 campaign 中记录身份；不把这些机器路径写回主线。Magic-capfix、共享 ngspice、Verilator 等仅在对应任务确实需要时安装和核对。
4. 从对应模块 README 选择一个不依赖本地历史波形的短卡，先一 worker 冒烟和一个压力点，再决定是否并行。沿用当前最多四个 ngspice 的限制；不要直接启动整 PLL 长仿真或已暂停的全量 RC 分支。
5. 每工况保留 deck、执行回执、实际终点、日志、指标和无损波形；复制完整工况归档到 Drive，核对 SHA256 后才算备份完成。不要直接搬空唯一的本地/运行时副本。

会话结束不等于工况完成。恢复只补缺失工况，必须同时检查执行、输入身份和真实 `t_end`。旧绝对路径 deck、机器配置变化后的冻结 campaign 不直接复用，也不批量重写旧结果；在云端建立新身份的 campaign。

默认 clone 不含历史原始结果、部分大图的 SVG 副本或本机归档软链接目标。文档/证据复核需要显式恢复对应资产包；源码可获取不等于所有历史结果已同步。参数与实验边界仍以[接手约定](../../AGENTS.md)、[当前状态](../status/current.md)和[执行计划](../status/prelayout_plan.md)为准。
