# WP-004：字入口固定相位可行区（可直接外发）

把已测单元延迟转成参数约束，作为字入口结构选择的第一步；不是动态串化模型或模拟验收。进入仓库根目录，读[工作包约定](README.md)。不运行ngspice，配额0。

## 固定输入

- `docs/data/tx_ingress_card.json` 的 `envelopes`：6条件×lean/reset，每条含 `clock_to_cml_min_ps/max_ps`、`tcq_min_ps/max_ps`，已合并两种静态MUX加载状态。
- `docs/design/tx_ingress.md`：负载和未测边界。
- `src/serdes_flow/balance.py`：复用已有约束评估。
- `docs/work_packages/deliveries/WP-002/evidence.json`：实际连接和旧激励事实。

无需读大raw或重写测量。首轮假定额外字时钟接收/缓冲延迟为0，只比较当前端口参考下的实测区间；真实时钟路径及其PVT变化未知，不插值未测角。

## 固定算法

对一种cell的第i个条件，数据到达区间为 `[a_i,b_i]`（ps）。同一个固定偏移φ必须使所有条件的区间落在假定安全窗 `[0,W]`：

```
phi_lo = max(-a_i)
phi_hi = min(W - b_i)
feasible = phi_lo <= phi_hi
minimum_window_ps = max(b_i) - min(a_i)
```

分别输出跨6条件，以及每种工艺内已测V/T条件的结果。后者不是新增校准功能，只帮助识别工艺内变化。W取 `50,100,150,200,250,500,1000` ps，都是假设扫描值，不是测得的实际更新窗或规格。字周期4000 ps，UI250 ps；工况间绝对延迟变化不能称为随机抖动或0.15 UI散布。

每个非空相位交集取中点φ，用 `serdes_flow.balance` 的 Fixed路径和Sample关系检查所有区间的两个端点：clock路径为空，data路径为 `Fixed(a_i+phi)` 或 `Fixed(b_i+phi)`；period4000、setup4000−W、hold0，Params的mismatch与tap_error均为0并标明未评估失配。只评估实测case的固定值；balance内部GRID复制同一确定值不代表45个独立PVT观测。不得以零值补未测角或声称全角通过。

## 唯一可写与复现

- `verification/work_packages/wp004_ingress_windows.py`，尽量≤120行，支持 `--output DIR`；
- `tests/test_ingress_windows.py`；
- `docs/work_packages/deliveries/WP-004/{evidence.json,summary.md,handoff.md}`。

数据契约沿用工作包约定，记录哈希、每个区间、各档W的相位交集、balance端点检查与未知项。保留无合法φ的情况。summary手写，一页以内。

```sh
uv run python verification/work_packages/wp004_ingress_windows.py --output docs/work_packages/deliveries/WP-004
uv run pytest -q tests/test_ingress_windows.py
uv run python -m serdes_flow.work_packages check WP-004
```

必要测试：区间 `[100,200]`、`[150,250]` 的最小窗宽为150；W100无交集，W200的交集为 `[-100,-50]`。等宽交集保留为零余量，不能说有设计裕量。错误单位、缺条件、min>max必须报错。

交接明确：尚未提供实际更新窗、字时钟电路、动态位映射或跨字一致性证明。两组8位的透明/保持结构涉及新负载和同沿保持竞争，需后续局部电路与动态模型；不能拿本card的clk→q最小值代替改负载后的保持证明。
