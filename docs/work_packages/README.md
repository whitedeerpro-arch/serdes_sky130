# 可委派工作包

工作包按模块交付，主 agent 负责接口、设计判断、证据复核和合入。执行者可以是较小模型：机械提取任务给定路径、算法、命令与停止条件，不要求通读项目或自行选择电路结构。

任务索引在 [config/work_packages.json](../../config/work_packages.json)。任务说明是完整的派发文本；执行者先读对应任务和本页，再读 [AGENTS.md](../../AGENTS.md)。本批默认共享当前工作区，不能以 `HEAD` 代替未提交的工作修订。

| 包 | 模块 | 难度 / 产物 | 状态 |
|---|---|---|---|
| [WP-001](WP-001-pll-waveform-audit.md) | PLL / 抽出 | 机械复核；两例原始波形及逐沿关系 | 以任务索引和 review 为准 |
| [WP-002](WP-002-tx-ingress-facts.md) | TX / 字捕获 | 提取与小模型；连接表、理想选择真值表、已知激励 | 以任务索引和 review 为准 |
| [WP-003](WP-003-rx-readout-lineage.md) | RX / 读出 | 机械清点；W40/W80 与各历史测试实际边界 | 以任务索引和 review 为准 |
| [WP-004](WP-004-tx-capture-model.md) | TX / 字捕获 | 参数约束；用已测延迟扫假定更新窗，复用balance | 已接受，见独立review |
| [WP-005](WP-005-tx-staggered-waveform-audit.md) | TX / 字捕获 | 机械波形复核；实际接收器、首级逐字/保持与启动失败对照 | 六压力结果已完整，可外发，0仿真配额 |

| [WP-006](WP-006-pll-4bit-coarse-plan.md) | PLL / 四位粗码 | 行为模型；测频有效性、±1限幅、冻结/故障/接管 | 旧测频搜索提案已被窗口式RTL替代，暂停派发；原数据保留 |

## 交付与权限

1. 每包只写自己的 `docs/work_packages/deliveries/WP-NNN/` 与任务指定的脚本。历史 `results/`、DUT、共享测量库、规格、模块状态和其他包的文件只读。执行者不提交、不切分支、不 reset/stash、不更新中央任务状态。
2. 首批三包不启动 ngspice、不联网，不使用“最新一次”或 `/tmp` 指针寻找输入。发现缺失、身份不符或测量函数不能处理时，在交付中列出并停止该项，保留其余独立结果。
3. 数据由正常 `.py` 脚本生成；`summary.md` 手写，所有结论带路径、字段或实例/行号。区分直接观察、计算、推断、未知。不得把历史修订的通过转给当前电路。
4. 每包提交 `evidence.json`、`summary.md`、`handoff.md`。JSON 至少含 `package_id`、`execution_status`、`inputs`、`observations`、`checks`、`unresolved`。`inputs` 是 `{path, sha256}` 列表；`observations` 可为命名对象或列表，`checks` 是 `{id, status, detail}` 列表，detail可为文字或含命名字段的对象，status 只能是 `pass/fail/ungraded/missing`。无数据写 null 与原因，不能补零或删去失败例。
5. `execution_status` 为 `complete/partial/blocked`，只表示工作包执行完整性；执行者没有设计签核或合入权限。交付注明改动文件、命令和退出结果、未做事项、建议 reviewer 检查点。
6. 波形/新运行需要明确起止时间、输入条件与单位。初值辅助求解、偏置就绪工作态、真实上电、闭环捕获必须分别表述。没有门槛的量保持 ungraded。

缺失的预期输入保留为 `{path, sha256: null, reason: "file missing"}`，检查器验证该路径确实缺失；若后来出现文件，旧交付会拒绝复用，需要重跑。不能删除缺失输入来让格式检查通过。

## 审查与 PR

状态顺序为 `ready → running → submitted → accepted / changes_requested`；未释放任务为 `waiting`。只有集成者能写 `docs/work_packages/reviews/WP-NNN.md` 并更新索引。`accepted` 是此包交付被接受，不意味着该模块满足全部规格。

审查顺序：检查输入身份与改动范围 → 独立重跑交付命令 → 抽查原始 deck/波形或实例 → 核实覆盖和未知项 → 判断能否进入模块当前结论。机械检查可自动化，工程结论由集成者负责。

本仓库暂未配置 remote。本地 review 单包含 PR 标题、具体改动、验证、结果与局限，作为当前审查产物；配置远端后可映射为实际 issue/PR。共享脏工作区不能直接从 HEAD 新建 worktree 后假定输入相同：外部分发必须携带依赖文件与哈希，或先由集成者建立包含相应工作修订的提交。

## 外部模型领取

在同一仓库环境中，把对应任务 Markdown 完整交给执行者；它包含固定路径和验收条件。可用 `uv run python -m serdes_flow.work_packages show WP-001` 输出派发文本，`check WP-001` 检查交付格式及输入哈希。命令检查不代替 reviewer 决定。

更复杂任务拆成“事实提取 → 约束/行为模型 → 局部电路实验 → 接口复核”，每步有独立包与输入。WP-004已给出基于单元实测、但不冒充动态设计证明的首轮约束；架构、规格/预算、电路更换和全局资源仍由集成者负责。

WP-005已有可携出的[资料包索引](../../results/catalog/work_package_wp005_bundle.json)：固定三批raw/deck/log及依赖，共323文件，gzip约76 MB；原包为 `results/work_packages/bundles/20261107T045327Z/WP-005-inputs.tar.gz`。包内逐文件SHA已回读验证，执行者按 `BUNDLE.md` 和任务文本只读复核，不需要PDK或仿真。它是打包时的固定输入，不能用之后中央文档的变动改写包内记录；任务仍待外部执行者领取。重新打包入口为 `verification/work_packages/bundle_wp005.py`，每次追加目录。

内部并行试用以明确的Terra任务为单位，使用短任务上下文，不自动复制完整会话或继续派生子agent。首批事实提取无需代码返工，历史清点暴露两处既有工具问题；约束模型修过一次实测浮点零宽边界。近期波形复核又指出预期翻转缺失会被忽略的问题，图脚本补过计划一致性和失败raw溯源。这些是逐包review记录，不是模型总体返工率或成本对照；实际计费未测。默认保留可外发任务，派发前指定执行器与文件范围。

仿真由集成者统一分配：本机全局ngspice最多4个，不能每个agent各自开4个。当前工作包都是0仿真配额；主agent的入口单元campaign限制2 worker。后续仿真包先写明配额、时限和续跑身份，再启动。

WP-006另有[小资料包索引](../../results/catalog/work_package_wp006_bundle.json)：27个输入文件，gzip约351 KiB，位于`results/work_packages/bundles/20261107T104040197072Z/WP-006-inputs.tar.gz`。只带135条件数字表、三组共同码补测小数据、任务与必要源码，不含raw/PDK；隔离解包后主提取器已成功复现。这是旧测频搜索提案的固定输入，现行策略已改用窗口式慢端逐码搜索；暂停派发，原交付partial、ngspice配额0；按包内BUNDLE.md执行，不运行需要大波形的`--tradeoff`。
