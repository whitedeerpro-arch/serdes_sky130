# Analog Sizing & Multi-Objective Optimization Toolkit

**结论。** 本仓库提供两阶段复用工具链，把 [尺寸设计流程](sizing.md) 的"器件物理定初值 + 多角代理优化 + 局部精修"落成纯 `numpy`/`scipy` 共享库，不引入外部 BO 依赖，并与 4 并发 `ngspice` 上限及意外重启续跑要求匹配：

1. **第一阶段（物理初值）：[`serdes_flow.gmid`](../../src/serdes_flow/gmid.py)** — SKY130A $g_m/I_D$ 查表、对数空间保单调 PCHIP 插值、`size_for_gm` / `size_for_id` 直接定尺寸、`snap_sky130_width` 对齐 DRC 指宽/指数组合，以及单角合并 DC/OP 表征 deck 生成器（`build_spice_char_deck`）。
2. **第二阶段（多角优化与精修）：[`serdes_flow.opt`](../../src/serdes_flow/opt.py)** — 单位超立方参数空间、Maximin LHS 采样、ARD/各向同性 Matérn-5/2 高斯过程、Kriging Believer 4 并发 Constrained Expected Improvement（cEI）、多角 Minimax 余量（`worst_corner_margin`）、精确非劣前沿（`pareto_front`）、带 SHA-256 身份校验和断点恢复的 `OptCampaign`（`trials.jsonl`），以及有界 Powell / Nelder-Mead 局部精修（`polish_local`）。

---

## 两阶段工作流

```text
规格 / 指标 ──► Stage 1: gmid.py (物理初值) ──► 参数范围 [low, high]
                    │                                   │
                    │  synthetic_ekv_table /            ▼
                    │  GmIdTable / DeviceCard     Stage 2: opt.py
                    │  size_for_gm / size_for_id   ├─ Maximin LHS 初始化
                    │  snap_sky130_width           ├─ 4 并发 cEI (Kriging Believer)
                    │                              ├─ worst_corner_margin (边界角→45角)
                    │                              ├─ trials.jsonl (SHA-256 续跑)
                    │                              └─ polish_local + pareto_front
```

### Stage 1：SKY130A $g_m/I_D$ 物理定尺寸（`serdes_flow.gmid`）

表征前可用内置解析 EKV 校准表（`synthetic_ekv_table`）做快速初值与单元测试；SPICE 表征后用 `GmIdTable.load(...)` 或 `GmIdTable.from_device_card(card)` 直接替换，接口完全一致。

```python
from serdes_flow import gmid

# 1. 初值阶段使用解析 EKV 参考表（零 ngspice）；校准后换为 GmIdTable.load(...)
table = gmid.synthetic_ekv_table(
    device_models=("nfet_01v8", "nfet_01v8_lvt", "pfet_01v8"),
    corners=("ss", "tt", "ff"),
    temps_c=(-40.0, 27.0, 85.0),
)

# 2. 按目标 gm 或 Id 直接综合器件尺寸与寄生
w_um, id_a, cgg_f, cdd_f, ro_ohm, vdsat_v, vgs_v = table.size_for_gm(
    gm_target=6e-3,
    gm_id_target=12.0,
    l_um=0.15,
    device_model="nfet_01v8",
    corner="ss",
    temp_c=85.0,
    vds_v=0.6,
)

# 3. 对齐 SKY130A DRC 指宽网格（默认 0.42..10.0 um，步进 0.01 um）
w_total, nf, w_finger = gmid.snap_sky130_width(w_um)
```

后续需要补齐 SPICE 器件表时，用 `build_spice_char_deck` 为每个工艺角生成单份合并 DC/OP 网表（单次加载 SKY130 模型库，调用本身不启动 `ngspice`）：

```python
deck_text = gmid.build_spice_char_deck(
    device_model="nfet_01v8",
    corner="tt",
    temp_c=(-40, 27, 85),
    l_list=(0.15, 0.25, 0.5, 1.0, 2.0),
    vds_list=(0.3, 0.6, 0.9, 1.2, 1.5),
)
```

### Stage 2：4 并发 cEI + 边界角 Minimax + 局部精修（`serdes_flow.opt`）

以 Stage 1 的物理初值为中心建立 `ParamSpace`，每轮取 `batch_size <= 4` 交给 4 并发 `spice.run_many`（先跑 [`corners.STRESS`](../../src/serdes_flow/corners.py) 边界压力角，收敛后再跑 45 条件全角复核）：

```python
from serdes_flow import opt

space = opt.ParamSpace([
    opt.ParamSpec("id_ma", 0.5, 3.0, log=True),
    opt.ParamSpec("w_um", 6.0, 50.0, log=True, step=0.05),
    opt.ParamSpec("r_ohm", 200.0, 800.0, step=10.0),
])

constraints = {
    "min_gain_db": (6.0, None),
    "min_bw_ghz": (2.8, None),
    "min_headroom_v": (0.18, None),
}

def eval_one(params: dict[str, float]) -> dict[str, float]:
    # 在此调用边界角 SPICE 评估并返回 corner_metrics: dict[corner_tag, dict[metric, float]]
    corner_metrics = run_stress_corners(params)
    report = opt.worst_corner_margin(
        corner_metrics,
        spec_bounds={"gain_db": (6.0, None), "bw_ghz": (2.8, None), "headroom_v": (0.18, None)},
        normalize=False,
    )
    return {
        "power_mw": 1.8 * params["id_ma"],
        "min_gain_db": min(m["gain_db"] for m in corner_metrics.values()),
        "min_bw_ghz": min(m["bw_ghz"] for m in corner_metrics.values()),
        "min_headroom_v": min(m["headroom_v"] for m in corner_metrics.values()),
        "worst_margin": report.worst_margin,
    }

# 断点续跑：重启后用相同 campaign_dir 重新打开，自动跳过已完成 SHA-256 试验
camp = opt.OptCampaign(
    "results/analog/<block>/opt/<run_id>",
    space,
    objective_key="power_mw",
    constraints=constraints,
    minimize_obj=True,
)
result = camp.run(
    eval_batch_fn=lambda batch: [eval_one(p) for p in batch],  # 可接入 4-worker spice.run_many
    n_trials=32,
    batch_size=4,
    init_points=8,
    polish=True,
    polish_method="Powell",
    polish_evals=25,
)

# 多目标权衡提取精确非劣前沿（底层复用 serdes_flow.robust_sizing.pareto_mask）
front = opt.pareto_front(
    [t.to_dict() for t in camp.trials],
    minimize_keys=("power_mw",),
    maximize_keys=("worst_margin",),
    constraints=constraints,
)
```

---

## 关键保障与约定

| 项目 | 实现行为 |
|---|---|
| 并发与资源 | `batch_size=4` 通过 Kriging Believer 虚拟观测避免同批候选坍缩到同一点，匹配本机 4 并发 `ngspice` 上限 |
| 崩溃恢复 | `OptCampaign` 每条试验立即追加刷新到 `trials.jsonl`；重启恢复时自动截断残留半行，并用 `campaign.json` 的 `config_sha256` 阻止参数空间/约束漂移的误续跑 |
| 重复去重 | 参数对齐步进网格后计算 `params_sha256`；BO 与 `polish_local` 均按哈希去重，不重复消耗 SPICE 仿真 |
| JSON 合规 | 非有限浮点（`NaN`/`Inf`）在写入 JSONL 前自动转为 `null`，与 [测量与结果约定](methods.md) 一致 |
| 离线自检 | `uv run pytest -q tests/test_gmid_opt.py`（零 `ngspice`，< 5 s） |

## 适用范围与假设

- `synthetic_ekv_table` 是用于初值估计与单元测试的解析 EKV 模型，不替代 SKY130 BSIM4 SPICE 器件卡与全角验证；最终定档必须通过对应模块的 SPICE 测试台 45 条件签核。
- `GmIdTable.from_device_card` 转换现有 `DeviceCard` 时，因旧卡片未保存 `cdd`，`cdd_w` 按 `cgd_w + 0.45 * (cgg_w - cgd_w)` 近似；高精度结电容需求应使用带 `cdd` 的新表征 deck。
- `GaussianProcess` 与 cEI 面向中小维度（$d \le 12$）、连续或较细离散网格的模拟电路参数优化；纯组合编码或大维度离散搜索应先用物理缩维或分层固定。
